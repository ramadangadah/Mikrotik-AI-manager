"""
Firmware push for CPEs.

RouterOS installs upgrades by having a valid .npk package sitting in the
device's file storage and then rebooting - there's no special "upload
firmware" API call, it's just "copy the file, then reboot". So the flow is:

  1. SFTP (SSH file transfer) the .npk into the device's root directory.
     This works for direct-reachable CPEs AND for isolated bridge-mode CPEs,
     by tunnelling the SFTP TCP connection through the management router's
     SOCKS proxy exactly like the API/REST connections are.
  2. Trigger a reboot through the normal RouterOS client.
  3. Poll the device until it comes back online and report the new version.

Paramiko (SFTP) is synchronous, so the actual transfer runs in a worker
thread via asyncio.to_thread and never blocks the event loop / other polls.
"""
from __future__ import annotations

import asyncio
import logging
import socket as socket_module
import time
from datetime import datetime, timezone

import paramiko
from python_socks import ProxyType
from python_socks.sync import Proxy as SyncSocksProxy
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.cpe import CPE
from app.models.firmware import FirmwareFile
from app.models.job import Job, JobStatus
from app.models.management_router import DeviceStatus, ManagementRouter
from app.services.device_connect import target_for_cpe
from app.services.routeros_client import RouterOSError, connect

logger = logging.getLogger(__name__)

SSH_PORT = 22
COME_BACK_ONLINE_TIMEOUT_S = 600
COME_BACK_ONLINE_POLL_INTERVAL_S = 10


def _sftp_upload_sync(cpe: CPE, router: ManagementRouter, local_path: str, remote_filename: str, ssh_port: int) -> None:
    from app.services.device_connect import target_for_cpe as _target  # local import, avoids cycle at module load

    target = _target(cpe, router)

    if target.relay:
        proxy = SyncSocksProxy.create(
            proxy_type=ProxyType.SOCKS5,
            host=target.relay.host,
            port=target.relay.port,
            username=target.relay.username,
            password=target.relay.password,
        )
        sock = proxy.connect(dest_host=target.host, dest_port=ssh_port, timeout=15)
    else:
        sock = socket_module.create_connection((target.host, ssh_port), timeout=15)

    transport = paramiko.Transport(sock)
    try:
        transport.connect(username=target.username, password=target.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            sftp.put(local_path, remote_filename)
        finally:
            sftp.close()
    finally:
        transport.close()


async def push_firmware(job_id: int, cpe_id: int, firmware_id: int, ssh_port: int = SSH_PORT) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        cpe = await db.get(CPE, cpe_id)
        firmware = await db.get(FirmwareFile, firmware_id)
        router = await db.get(ManagementRouter, cpe.management_router_id) if cpe else None

        if not (job and cpe and firmware and router):
            if job:
                job.status = JobStatus.failed
                job.log = "Missing CPE, firmware file, or management router."
                job.finished_at = datetime.now(timezone.utc)
                db.add(job)
                await db.commit()
            return

        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5
        job.log = f"Uploading {firmware.filename} to {cpe.name} ({cpe.host}) via SFTP...\n"
        db.add(job)
        await db.commit()

        try:
            remote_name = firmware.filename if firmware.filename.endswith(".npk") else f"{firmware.filename}.npk"
            await asyncio.to_thread(_sftp_upload_sync, cpe, router, firmware.stored_path, remote_name, ssh_port)

            job.progress = 50
            job.log += "Upload complete. Rebooting device to apply the package...\n"
            db.add(job)
            await db.commit()

            target = target_for_cpe(cpe, router)
            async with connect(target) as ros:
                await ros.run_action("system", "reboot")

            job.progress = 60
            job.log += "Reboot triggered. Waiting for device to come back online...\n"
            db.add(job)
            await db.commit()

            came_back, new_version = await _wait_for_recovery(cpe, router)

            job = await db.get(Job, job_id)
            cpe = await db.get(CPE, cpe_id)
            if came_back:
                job.status = JobStatus.success
                job.progress = 100
                job.log += f"Device back online running version {new_version}.\n"
                cpe.status = DeviceStatus.online
                cpe.routeros_version = new_version or cpe.routeros_version
            else:
                job.status = JobStatus.failed
                job.log += (
                    f"Device did not come back online within {COME_BACK_ONLINE_TIMEOUT_S}s. "
                    "It may still be rebooting, or may need manual/console recovery. "
                    "Consider staging upgrades one device at a time until you're confident "
                    "in a given firmware version for this hardware model.\n"
                )
                cpe.status = DeviceStatus.offline
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            db.add(cpe)
            await db.commit()

        except Exception as e:
            logger.exception("firmware push failed for cpe %s", cpe_id)
            job = await db.get(Job, job_id)
            job.status = JobStatus.failed
            job.log = (job.log or "") + f"\nERROR: {e}\n"
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            await db.commit()


async def _wait_for_recovery(cpe: CPE, router: ManagementRouter) -> tuple[bool, str | None]:
    deadline = time.monotonic() + COME_BACK_ONLINE_TIMEOUT_S
    # Give it a head start - a reboot + package install is not instantaneous.
    await asyncio.sleep(30)
    while time.monotonic() < deadline:
        try:
            target = target_for_cpe(cpe, router)
            async with connect(target) as ros:
                info = await ros.get_single("system/resource")
                return True, info.get("version")
        except (RouterOSError, OSError, asyncio.TimeoutError):
            await asyncio.sleep(COME_BACK_ONLINE_POLL_INTERVAL_S)
    return False, None
