"""
Pulls a RouterOS binary backup (`/system/backup/save`) off a device via SFTP
and stores it locally, timestamped. Same SOCKS-relay-aware transfer pattern
as firmware_service.py, just in the opposite direction.

Also handles the reverse trip: pushing a stored backup back onto a device
and telling RouterOS to load it (`/system/backup/load`), which is how a CPE
that got factory-reset or physically swapped for a spare in the field can be
brought back to its exact previous configuration - either by hand (the
restore-now endpoint) or automatically the moment it's seen coming back
online again (see `maybe_auto_restore` and CPE.auto_restore_on_reconnect).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket as socket_module
import time
from datetime import datetime, timezone

import paramiko
from python_socks import ProxyType
from python_socks.sync import Proxy as SyncSocksProxy
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.config_backup import BackupTargetType, ConfigBackup
from app.models.cpe import CPE
from app.models.job import Job, JobStatus, JobType, TargetType
from app.models.management_router import DeviceStatus, ManagementRouter
from app.services import audit
from app.services.device_connect import target_for_cpe, target_for_management_router
from app.services.routeros_client import RouterOSError, connect

logger = logging.getLogger(__name__)
settings = get_settings()

RESTORE_COME_BACK_ONLINE_TIMEOUT_S = 600
RESTORE_COME_BACK_ONLINE_POLL_INTERVAL_S = 10


def _download_sync(target, remote_filename: str, local_path: str, ssh_port: int = 22) -> None:
    if target.relay:
        proxy = SyncSocksProxy.create(
            proxy_type=ProxyType.SOCKS5, host=target.relay.host, port=target.relay.port,
            username=target.relay.username, password=target.relay.password,
        )
        sock = proxy.connect(dest_host=target.host, dest_port=ssh_port, timeout=15)
    else:
        sock = socket_module.create_connection((target.host, ssh_port), timeout=15)

    transport = paramiko.Transport(sock)
    try:
        transport.connect(username=target.username, password=target.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            sftp.get(remote_filename, local_path)
        finally:
            sftp.close()
    finally:
        transport.close()


async def backup_management_router(db: AsyncSession, router: ManagementRouter) -> ConfigBackup:
    return await _backup(db, target_for_management_router(router), BackupTargetType.management_router, router.id, router.name)


async def backup_cpe(db: AsyncSession, cpe: CPE, router: ManagementRouter) -> ConfigBackup:
    return await _backup(db, target_for_cpe(cpe, router), BackupTargetType.cpe, cpe.id, cpe.name)


async def _backup(db: AsyncSession, target, target_type: BackupTargetType, target_id: int, target_name: str) -> ConfigBackup:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    remote_name = f"auto-{timestamp}"

    async with connect(target) as ros:
        await ros.run_action("system/backup", "save", name=remote_name)
        info = await ros.get_single("system/resource")

    safe_target = "".join(c if c.isalnum() or c in "-_." else "_" for c in target_name)
    out_dir = os.path.join(settings.BACKUP_DIR, f"{target_type.value}-{target_id}-{safe_target}")
    os.makedirs(out_dir, exist_ok=True)
    local_path = os.path.join(out_dir, f"{remote_name}.backup")

    await asyncio.sleep(2)  # give RouterOS a moment to finish writing the file
    await asyncio.to_thread(_download_sync, target, f"{remote_name}.backup", local_path)

    size = os.path.getsize(local_path) if os.path.exists(local_path) else None
    backup = ConfigBackup(
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        stored_path=local_path,
        size_bytes=size,
        routeros_version=info.get("version"),
    )
    db.add(backup)
    await db.commit()
    await db.refresh(backup)
    return backup


def _upload_sync(target, local_path: str, remote_filename: str, ssh_port: int = 22) -> None:
    if target.relay:
        proxy = SyncSocksProxy.create(
            proxy_type=ProxyType.SOCKS5, host=target.relay.host, port=target.relay.port,
            username=target.relay.username, password=target.relay.password,
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


async def _wait_for_restore_recovery(target) -> tuple[bool, str | None]:
    deadline = time.monotonic() + RESTORE_COME_BACK_ONLINE_TIMEOUT_S
    # /system/backup/load reboots the device to apply the restored config -
    # give it a head start before polling, same as a firmware push.
    await asyncio.sleep(30)
    while time.monotonic() < deadline:
        try:
            async with connect(target) as ros:
                info = await ros.get_single("system/resource")
                return True, info.get("version")
        except (RouterOSError, OSError, asyncio.TimeoutError):
            await asyncio.sleep(RESTORE_COME_BACK_ONLINE_POLL_INTERVAL_S)
    return False, None


async def execute_restore_job(job_id: int, backup_id: int, target_type: str, target_id: int, ssh_port: int = 22) -> None:
    """
    Runs as a background Job: uploads `backup_id`'s stored .backup file to
    the device named by (target_type, target_id) via SFTP, then triggers
    `/system/backup/load` on it - RouterOS restores that exact config and
    reboots on its own. Works for bridge-mode/isolated CPEs the same way
    firmware pushes do (SOCKS relay or VPN tunnel, whichever the device is
    already configured to use), since it reuses the same ConnectionTarget.

    Caveat worth knowing: a restored backup can include a different admin
    username/password than the one currently on file for this device (e.g.
    if it was changed since that backup was taken) - if the device doesn't
    come back reachable with its current saved credentials, that's usually
    why; the config was still restored, it just needs its credentials in
    this app updated to match.
    """
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        backup = await db.get(ConfigBackup, backup_id)
        if not job or not backup:
            return

        cpe: CPE | None = None
        target = None
        label = None
        if target_type == "cpe":
            cpe = await db.get(CPE, target_id)
            if cpe:
                router = await db.get(ManagementRouter, cpe.management_router_id)
                if router:
                    target = target_for_cpe(cpe, router)
                label = cpe.name
        else:
            router = await db.get(ManagementRouter, target_id)
            if router:
                target = target_for_management_router(router)
                label = router.name

        if not target:
            job.status = JobStatus.failed
            job.log = "Target device not found, or has no host/credentials configured."
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            await db.commit()
            return

        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        job.progress = 5
        job.log = f"Uploading {os.path.basename(backup.stored_path)} to {label} via SFTP...\n"
        db.add(job)
        await db.commit()

        try:
            remote_name = "app-restore.backup"
            await asyncio.to_thread(_upload_sync, target, backup.stored_path, remote_name, ssh_port)

            job.progress = 50
            job.log += "Upload complete. Loading backup (device will reboot automatically)...\n"
            db.add(job)
            await db.commit()

            async with connect(target) as ros:
                await ros.run_action("system/backup", "load", name=remote_name)

            job.progress = 60
            job.log += "Restore triggered. Waiting for the device to come back online...\n"
            db.add(job)
            await db.commit()

            came_back, new_version = await _wait_for_restore_recovery(target)

            job = await db.get(Job, job_id)
            if came_back:
                job.status = JobStatus.success
                job.progress = 100
                job.log += f"Device back online after config restore, running version {new_version}.\n"
                if target_type == "cpe":
                    cpe = await db.get(CPE, target_id)
                    if cpe:
                        cpe.status = DeviceStatus.online
                        cpe.last_restore_job_id = job.id
                        db.add(cpe)
            else:
                job.status = JobStatus.failed
                job.log += (
                    f"Device did not come back reachable within {RESTORE_COME_BACK_ONLINE_TIMEOUT_S}s after "
                    "the restore. It may still be rebooting, or the restored config changed its management "
                    "IP/admin credentials - check the device directly and update its entry here if so.\n"
                )
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            await db.commit()

        except Exception as e:
            logger.exception("config restore failed for backup %s -> %s %s", backup_id, target_type, target_id)
            job = await db.get(Job, job_id)
            job.status = JobStatus.failed
            job.log = (job.log or "") + f"\nERROR: {e}\n"
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            await db.commit()


async def restore_now(db: AsyncSession, backup: ConfigBackup, ssh_port: int = 22, created_by: str | None = None) -> Job:
    """Creates and launches a restore Job for an operator-triggered restore
    (as opposed to the automatic reconnect-triggered path below)."""
    from app.services.job_runner import launch  # local import: job_runner has no reason to import this module back

    target_type = TargetType.cpe if backup.target_type == BackupTargetType.cpe else TargetType.management_router
    job = Job(
        job_type=JobType.config_restore,
        target_type=target_type,
        target_id=backup.target_id,
        status=JobStatus.pending,
        created_by=created_by,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    launch(execute_restore_job(job.id, backup.id, target_type.value, backup.target_id, ssh_port=ssh_port))
    return job


async def maybe_auto_restore(cpe_id: int) -> None:
    """
    Called by the poller the moment a CPE is observed flipping from offline
    back to online. If that CPE has auto_restore_on_reconnect enabled and
    has at least one stored backup, automatically restores its last known
    config - handy for antennas that get factory-reset or physically
    swapped for a spare in the field and would otherwise come back up with
    blank/default configuration until someone notices.

    Runs in its own DB session/background task (via job_runner), fully
    decoupled from the poller's own batch-commit transaction.
    """
    from app.services.job_runner import launch  # local import, same reason as above

    async with AsyncSessionLocal() as db:
        cpe = await db.get(CPE, cpe_id)
        if not cpe or not cpe.auto_restore_on_reconnect:
            return

        result = await db.execute(
            select(ConfigBackup)
            .where(ConfigBackup.target_type == BackupTargetType.cpe, ConfigBackup.target_id == cpe_id)
            .order_by(ConfigBackup.created_at.desc())
            .limit(1)
        )
        backup = result.scalar_one_or_none()
        if not backup:
            logger.info("cpe %s has auto_restore_on_reconnect set but no stored backup yet - skipping", cpe_id)
            return

        job = Job(
            job_type=JobType.config_restore,
            target_type=TargetType.cpe,
            target_id=cpe_id,
            status=JobStatus.pending,
            created_by="auto-restore-on-reconnect",
        )
        db.add(job)
        await audit.record(
            db, "system", "config_auto_restore_triggered", target=cpe.name,
            details=f"restoring backup #{backup.id} from {backup.created_at.isoformat()}", commit=False,
        )
        await db.commit()
        await db.refresh(job)

    launch(execute_restore_job(job.id, backup.id, "cpe", cpe_id))
