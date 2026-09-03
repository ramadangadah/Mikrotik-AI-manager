from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.cpe import CPE
from app.models.job import Job, JobStatus, JobType, TargetType
from app.models.management_router import ManagementRouter
from app.models.user import User
from app.schemas.job import JobOut
from app.services import audit
from app.services.job_runner import launch
from app.services.script_service import execute_script_job

router = APIRouter(prefix="/api/scripts", tags=["scripts"], dependencies=[Depends(require_password_set)])

# Any selection that resolves to more than this many devices must pass
# confirm=true - a fat-fingered "run on all CPEs" should never be one
# accidental click/request away, since this executes arbitrary RouterOS
# commands on real hardware.
MAX_UNCONFIRMED_TARGETS = 1


class ScriptRunRequest(BaseModel):
    source: str = Field(min_length=1, description='RouterOS script body, e.g. `:log info "hello"` or a full script')

    # Selection - set exactly one of these to say what this script runs on.
    cpe_id: int | None = None                      # a single CPE
    cpe_ids: list[int] | None = None                # an explicit set of CPEs
    management_router_id: int | None = None         # the management router itself (not its CPEs)
    network_id: int | None = None                   # bulk: every monitored CPE in this network
    all_cpes_under_router_id: int | None = None      # bulk: every monitored CPE under this management router
    all_monitored_cpes: bool = False                 # bulk: every monitored CPE in the whole system

    confirm: bool = False  # required once the resolved target list has more than one device


async def _resolve_targets(payload: ScriptRunRequest, db: AsyncSession) -> list[tuple[TargetType, int, str]]:
    """Returns [(TargetType, id, label), ...] for whichever selection field was set."""
    if payload.cpe_id is not None:
        cpe = await db.get(CPE, payload.cpe_id)
        if not cpe:
            raise HTTPException(status_code=404, detail="CPE not found")
        return [(TargetType.cpe, cpe.id, cpe.name)]

    if payload.cpe_ids:
        result = await db.execute(select(CPE).where(CPE.id.in_(payload.cpe_ids)))
        cpes = result.scalars().all()
        missing = set(payload.cpe_ids) - {c.id for c in cpes}
        if missing:
            raise HTTPException(status_code=404, detail=f"CPE ids not found: {sorted(missing)}")
        return [(TargetType.cpe, c.id, c.name) for c in cpes]

    if payload.management_router_id is not None:
        mr = await db.get(ManagementRouter, payload.management_router_id)
        if not mr:
            raise HTTPException(status_code=404, detail="Management router not found")
        return [(TargetType.management_router, mr.id, mr.name)]

    if payload.network_id is not None:
        result = await db.execute(select(CPE).where(CPE.network_id == payload.network_id, CPE.monitored.is_(True)))
        return [(TargetType.cpe, c.id, c.name) for c in result.scalars().all()]

    if payload.all_cpes_under_router_id is not None:
        result = await db.execute(
            select(CPE).where(CPE.management_router_id == payload.all_cpes_under_router_id, CPE.monitored.is_(True))
        )
        return [(TargetType.cpe, c.id, c.name) for c in result.scalars().all()]

    if payload.all_monitored_cpes:
        result = await db.execute(select(CPE).where(CPE.monitored.is_(True)))
        return [(TargetType.cpe, c.id, c.name) for c in result.scalars().all()]

    raise HTTPException(
        status_code=400,
        detail=(
            "No target selected - set one of cpe_id, cpe_ids, management_router_id, network_id, "
            "all_cpes_under_router_id, or all_monitored_cpes."
        ),
    )


@router.post("/run", response_model=list[JobOut], status_code=202)
async def run_script(payload: ScriptRunRequest, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    """
    Runs a RouterOS script on one CPE, an explicit set of CPEs, a management
    router itself, or a bulk selection (a whole network, every CPE under a
    management router, or every monitored CPE) - launches one background Job
    per target device so progress/output/failures can be tracked
    individually via GET /api/jobs. This is the same execution primitive the
    AI assistant proposes; the assistant never calls it itself - a human
    always confirms first, through this same audited endpoint.
    """
    targets = await _resolve_targets(payload, db)
    if not targets:
        raise HTTPException(status_code=400, detail="No devices matched that selection - nothing to run on.")
    if len(targets) > MAX_UNCONFIRMED_TARGETS and not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail=f"This would run on {len(targets)} devices - set confirm=true to proceed.",
        )

    jobs: list[Job] = []
    for target_type, target_id, _label in targets:
        job = Job(
            job_type=JobType.run_script,
            target_type=target_type,
            target_id=target_id,
            status=JobStatus.pending,
            created_by=user.username,
        )
        db.add(job)
        jobs.append(job)

    preview = payload.source if len(payload.source) <= 200 else payload.source[:200] + "..."
    await audit.record(db, user.username, "script_run_started", target=f"{len(jobs)} device(s)", details=preview, commit=False)
    await db.commit()

    for job in jobs:
        await db.refresh(job)
        launch(execute_script_job(job.id, job.target_type.value, job.target_id, payload.source))

    return jobs
