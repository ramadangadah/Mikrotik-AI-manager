"""
Runs an arbitrary RouterOS script (the same language you'd type into
Winbox's terminal or a `/system script`) on a CPE or management router,
through whatever connection path is already configured for it (direct,
SOCKS relay, or VPN tunnel) - no new plumbing needed there.

RouterOS's API has no notion of "run this ad-hoc command and stream me
stdout" - console output only exists in Winbox/SSH. The closest thing the
API offers is: save the text as a named script, run it, then read it back
out of /log if the script logged anything (`:log info "..."`). So that's
what we do: create a throwaway script, run it, best-effort collect recent
log output, then delete the script again. For scripts that don't call
`:log`, success/failure (did it trap an error) is still meaningful signal.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.models.cpe import CPE
from app.models.job import Job, JobStatus
from app.models.management_router import ManagementRouter
from app.services.device_connect import target_for_cpe, target_for_management_router
from app.services.routeros_client import ConnectionTarget, RouterOSError, connect

logger = logging.getLogger(__name__)


async def run_script(target: ConnectionTarget, source: str) -> dict:
    name = f"app-adhoc-{uuid.uuid4().hex[:10]}"
    async with connect(target) as ros:
        created = await ros.create("system/script", name=name, source=source)
        script_id = created.get(".id") or created.get("ret")
        if not script_id:
            raise RouterOSError(f"script creation did not return an id (got: {created})")

        run_error = None
        try:
            await ros.run_action("system/script", "run", **{".id": script_id})
        except RouterOSError as e:
            run_error = str(e)
        finally:
            try:
                await ros.remove("system/script", script_id)
            except Exception:
                pass

        if run_error:
            raise RouterOSError(run_error)

        log_tail = ""
        try:
            logs = await ros.list("log")
            recent = logs[-20:] if isinstance(logs, list) else []
            log_tail = "\n".join(
                f"{r.get('time', '')} [{r.get('topics', '')}] {r.get('message', '')}" for r in recent
            )
        except Exception:
            pass

    return {"script_name": name, "log_tail": log_tail}


async def execute_script_job(job_id: int, target_type: str, target_id: int, source: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if not job:
            return
        job.status = JobStatus.running
        job.started_at = datetime.now(timezone.utc)
        db.add(job)
        await db.commit()

        try:
            if target_type == "cpe":
                cpe = await db.get(CPE, target_id)
                if not cpe:
                    raise RouterOSError("CPE not found")
                router = await db.get(ManagementRouter, cpe.management_router_id)
                target = target_for_cpe(cpe, router)
                label = cpe.name
            else:
                router = await db.get(ManagementRouter, target_id)
                if not router:
                    raise RouterOSError("Management router not found")
                target = target_for_management_router(router)
                label = router.name

            result = await run_script(target, source)

            job = await db.get(Job, job_id)
            job.status = JobStatus.success
            job.progress = 100
            job.log = f"Ran on {label}.\n\nRecent log output:\n{result['log_tail'] or '(script produced no :log output)'}"
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            await db.commit()
        except Exception as e:
            logger.info("script run failed for %s %s: %s", target_type, target_id, e)
            job = await db.get(Job, job_id)
            job.status = JobStatus.failed
            job.log = f"ERROR: {e}"
            job.finished_at = datetime.now(timezone.utc)
            db.add(job)
            await db.commit()
