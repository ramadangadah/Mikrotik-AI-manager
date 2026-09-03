from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.alert import Alert, AlertStatus
from app.models.user import User
from app.schemas.alert import AlertOut
from app.services.prediction_service import run_prediction_cycle

router = APIRouter(prefix="/api/alerts", tags=["alerts"], dependencies=[Depends(require_password_set)])


@router.get("", response_model=list[AlertOut])
async def list_alerts(
    status_filter: str | None = None,
    severity: str | None = None,
    cpe_id: int | None = None,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
):
    query = select(Alert)
    if status_filter:
        query = query.where(Alert.status == status_filter)
    if severity:
        query = query.where(Alert.severity == severity)
    if cpe_id:
        query = query.where(Alert.cpe_id == cpe_id)
    query = query.order_by(Alert.created_at.desc()).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{alert_id}/acknowledge", response_model=AlertOut)
async def acknowledge(alert_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.acknowledged
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/resolve", response_model=AlertOut)
async def resolve(alert_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    alert = await db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = AlertStatus.resolved
    alert.resolved_at = datetime.now(timezone.utc)
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


@router.post("/evaluate-now")
async def evaluate_now(full: bool = True, user: User = Depends(require_operator)):
    """Manually trigger a prediction/alerting pass instead of waiting for the schedule."""
    return await run_prediction_cycle(full=full)
