"""
The polling engine. Runs on a schedule (see scheduler.py) and also on
demand ("poll now" from the UI). Bounded concurrency keeps resource usage
predictable even with thousands of CPEs on a small VM: only
POLL_CONCURRENCY devices are ever being talked to at once, the rest queue.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.cpe import CPE
from app.models.management_router import DeviceStatus, ManagementRouter
from app.models.metric import Granularity, MetricSample, MetricType
from app.services.device_connect import target_for_cpe, target_for_management_router
from app.services.routeros_client import RouterOSError, connect

logger = logging.getLogger(__name__)
settings = get_settings()

# In-memory consecutive-failure counters, used only to debounce flapping
# offline/online flips. Not persisted - fine to reset on restart.
_fail_counts: dict[tuple[str, int], int] = defaultdict(int)
OFFLINE_AFTER_N_FAILURES = 2


def _sum_interface_errors(interfaces: list[dict]) -> float:
    total = 0.0
    for i in interfaces:
        for key in ("rx-error", "tx-error", "rx-drop", "tx-drop"):
            try:
                total += float(i.get(key, 0) or 0)
            except (TypeError, ValueError):
                pass
    return total


async def _record(db: AsyncSession, cpe_id: int, metric_type: MetricType, value: float | None, iface: str | None = None):
    if value is None:
        return
    db.add(
        MetricSample(
            cpe_id=cpe_id,
            metric_type=metric_type,
            granularity=Granularity.raw,
            value=value,
            interface_name=iface,
        )
    )


async def poll_management_router(db: AsyncSession, router: ManagementRouter) -> bool:
    target = target_for_management_router(router)
    started = time.monotonic()
    try:
        async with connect(target) as ros:
            resource = await ros.get_single("system/resource")
            identity = await ros.get_single("system/identity")
            rtt_ms = (time.monotonic() - started) * 1000

        router.identity = identity.get("name") if identity else router.identity
        router.routeros_version = resource.get("version", router.routeros_version)
        router.board_name = resource.get("board-name", router.board_name)
        router.status = DeviceStatus.online
        router.last_seen = datetime.now(timezone.utc)
        router.last_error = None
        db.add(router)
        _fail_counts[("router", router.id)] = 0
        logger.debug("polled management router %s in %.0fms", router.name, rtt_ms)
        return True
    except (RouterOSError, OSError, asyncio.TimeoutError) as e:
        key = ("router", router.id)
        _fail_counts[key] += 1
        if _fail_counts[key] >= OFFLINE_AFTER_N_FAILURES:
            router.status = DeviceStatus.offline
        router.last_error = str(e)[:500]
        db.add(router)
        logger.warning("failed polling management router %s: %s", router.name, e)
        return False


async def poll_cpe(db: AsyncSession, cpe: CPE, router: ManagementRouter) -> bool:
    if cpe.connection_mode.value == "unmanaged" or not cpe.host:
        return False  # nothing to poll until credentials/host are set

    target = target_for_cpe(cpe, router)
    started = time.monotonic()
    try:
        async with connect(target) as ros:
            resource = await ros.get_single("system/resource")
            rtt_ms = (time.monotonic() - started) * 1000

            interfaces: list[dict] = []
            try:
                interfaces = await ros.list("interface")
            except RouterOSError:
                pass

            wireless: list[dict] = []
            try:
                wireless = await ros.list("interface/wireless/registration-table")
            except RouterOSError:
                pass
            if not wireless:
                try:
                    wireless = await ros.list("interface/wireless/monitor")
                except RouterOSError:
                    pass

            pppoe_running = None
            try:
                pppoe_clients = await ros.list("interface/pppoe-client")
                if pppoe_clients:
                    pppoe_running = any(str(p.get("running")).lower() == "true" for p in pppoe_clients)
            except RouterOSError:
                pass

        cpu = resource.get("cpu-load")
        total_mem = resource.get("total-memory")
        free_mem = resource.get("free-memory")
        mem_percent = None
        if total_mem and free_mem is not None:
            try:
                total_mem, free_mem = float(total_mem), float(free_mem)
                if total_mem > 0:
                    mem_percent = round((1 - free_mem / total_mem) * 100, 1)
            except (TypeError, ValueError):
                pass

        signal = None
        ccq = None
        if wireless:
            w0 = wireless[0]
            for key in ("signal-strength", "rx-signal"):
                if key in w0:
                    try:
                        signal = float(str(w0[key]).replace("dBm", "").strip())
                    except (TypeError, ValueError):
                        pass
                    break
            if "tx-ccq" in w0:
                try:
                    ccq = float(w0["tx-ccq"])
                except (TypeError, ValueError):
                    pass

        error_total = _sum_interface_errors(interfaces) if interfaces else None

        await _record(db, cpe.id, MetricType.cpu_percent, float(cpu) if cpu is not None else None)
        await _record(db, cpe.id, MetricType.memory_percent, mem_percent)
        await _record(db, cpe.id, MetricType.signal_dbm, signal)
        await _record(db, cpe.id, MetricType.ccq_percent, ccq)
        await _record(db, cpe.id, MetricType.interface_errors, error_total)
        await _record(db, cpe.id, MetricType.ping_latency_ms, rtt_ms)
        if pppoe_running is not None:
            await _record(db, cpe.id, MetricType.pppoe_online, 1.0 if pppoe_running else 0.0)

        cpe.last_cpu_percent = float(cpu) if cpu is not None else cpe.last_cpu_percent
        cpe.last_memory_percent = mem_percent if mem_percent is not None else cpe.last_memory_percent
        cpe.last_signal_dbm = signal if signal is not None else cpe.last_signal_dbm
        cpe.last_ccq_percent = ccq if ccq is not None else cpe.last_ccq_percent
        cpe.last_ping_ms = rtt_ms
        cpe.routeros_version = resource.get("version", cpe.routeros_version)
        try:
            cpe.uptime_seconds = _parse_uptime(resource.get("uptime"))
        except Exception:
            pass
        was_offline = cpe.status == DeviceStatus.offline
        cpe.status = DeviceStatus.online
        cpe.last_seen = datetime.now(timezone.utc)
        cpe.last_error = None
        db.add(cpe)
        _fail_counts[("cpe", cpe.id)] = 0

        if was_offline and cpe.auto_restore_on_reconnect:
            # Decoupled from this poll's own session/transaction on purpose -
            # runs as its own background job, see config_backup_service.
            from app.services.config_backup_service import maybe_auto_restore
            from app.services.job_runner import launch

            launch(maybe_auto_restore(cpe.id))

        return True
    except (RouterOSError, OSError, asyncio.TimeoutError, ValueError) as e:
        key = ("cpe", cpe.id)
        _fail_counts[key] += 1
        if _fail_counts[key] >= OFFLINE_AFTER_N_FAILURES:
            cpe.status = DeviceStatus.offline
        cpe.last_error = str(e)[:500]
        db.add(cpe)
        logger.info("failed polling cpe %s (%s): %s", cpe.name, cpe.host, e)
        return False


def _parse_uptime(uptime_str: str | None) -> int | None:
    """RouterOS formats uptime like '3w4d5h6m7s' or '1d02:03:04'. Best-effort parse."""
    if not uptime_str:
        return None
    total = 0
    num = ""
    for ch in uptime_str:
        if ch.isdigit():
            num += ch
        else:
            if not num:
                continue
            n = int(num)
            total += {"w": n * 604800, "d": n * 86400, "h": n * 3600, "m": n * 60, "s": n}.get(ch, 0)
            num = ""
    return total or None


class PollingEngine:
    def __init__(self):
        self._semaphore = asyncio.Semaphore(settings.POLL_CONCURRENCY)

    async def _bounded(self, coro):
        async with self._semaphore:
            return await coro

    async def poll_all_once(self) -> dict:
        async with AsyncSessionLocal() as db:
            routers = (await db.execute(select(ManagementRouter))).scalars().all()
            router_tasks = [self._bounded(poll_management_router(db, r)) for r in routers]
            router_results = await asyncio.gather(*router_tasks, return_exceptions=True)
            await db.commit()

            cpes = (await db.execute(select(CPE).where(CPE.monitored.is_(True)))).scalars().all()
            router_by_id = {r.id: r for r in routers}
            cpe_tasks = []
            for cpe in cpes:
                router = router_by_id.get(cpe.management_router_id)
                if not router:
                    continue
                cpe_tasks.append(self._bounded(poll_cpe(db, cpe, router)))
            cpe_results = await asyncio.gather(*cpe_tasks, return_exceptions=True)
            await db.commit()

        return {
            "routers_polled": len(router_results),
            "routers_ok": sum(1 for r in router_results if r is True),
            "cpes_polled": len(cpe_results),
            "cpes_ok": sum(1 for r in cpe_results if r is True),
        }


polling_engine = PollingEngine()
