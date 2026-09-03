from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.alert import Alert, AlertStatus, Severity
from app.models.cpe import CPE
from app.models.management_router import DeviceStatus, ManagementRouter
from app.models.network import Network
from app.models.user import User
from app.services.polling_service import polling_engine
from app.services.prediction_service import run_prediction_cycle

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_password_set)])


@router.post("/poll-now")
async def poll_now(user: User = Depends(require_operator)):
    """Runs one polling + alerting cycle immediately instead of waiting for the schedule."""
    poll_result = await polling_engine.poll_all_once()
    prediction_result = await run_prediction_cycle(full=True)
    return {"poll": poll_result, "prediction": prediction_result}


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db)):
    total_routers = await db.scalar(select(func.count()).select_from(ManagementRouter))
    online_routers = await db.scalar(select(func.count()).select_from(ManagementRouter).where(ManagementRouter.status == DeviceStatus.online))
    total_networks = await db.scalar(select(func.count()).select_from(Network))
    total_cpes = await db.scalar(select(func.count()).select_from(CPE))
    online_cpes = await db.scalar(select(func.count()).select_from(CPE).where(CPE.status == DeviceStatus.online))
    offline_cpes = await db.scalar(select(func.count()).select_from(CPE).where(CPE.status == DeviceStatus.offline))
    unmanaged_cpes = await db.scalar(select(func.count()).select_from(CPE).where(CPE.connection_mode == "unmanaged"))
    pppoe_cpes = await db.scalar(select(func.count()).select_from(CPE).where(CPE.pppoe_enabled.is_(True)))
    bridge_cpes = await db.scalar(select(func.count()).select_from(CPE).where(CPE.bridge_mode.is_(True)))

    open_alerts = await db.scalar(select(func.count()).select_from(Alert).where(Alert.status != AlertStatus.resolved))
    critical_alerts = await db.scalar(
        select(func.count()).select_from(Alert).where(Alert.status != AlertStatus.resolved, Alert.severity == Severity.critical)
    )
    predictive_alerts = await db.scalar(
        select(func.count()).select_from(Alert).where(Alert.status != AlertStatus.resolved, Alert.is_prediction.is_(True))
    )

    by_router = (
        await db.execute(
            select(ManagementRouter.id, ManagementRouter.name, ManagementRouter.status, func.count(CPE.id))
            .outerjoin(CPE, CPE.management_router_id == ManagementRouter.id)
            .group_by(ManagementRouter.id)
        )
    ).all()

    return {
        "management_routers": {"total": total_routers, "online": online_routers},
        "networks": {"total": total_networks},
        "cpes": {
            "total": total_cpes,
            "online": online_cpes,
            "offline": offline_cpes,
            "unmanaged": unmanaged_cpes,
            "pppoe": pppoe_cpes,
            "bridge_mode": bridge_cpes,
        },
        "alerts": {"open": open_alerts, "critical": critical_alerts, "predictive": predictive_alerts},
        "routers_overview": [
            {"id": r_id, "name": name, "status": status, "cpe_count": count} for r_id, name, status, count in by_router
        ],
    }
