from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertCategory, AlertStatus, Severity
from app.services.notify import notify_alert
from app.services.runtime_settings import EffectiveSettings, get_effective

_SEVERITY_RANK = {Severity.info: 0, Severity.warning: 1, Severity.critical: 2}


async def upsert_alert(
    db: AsyncSession,
    *,
    cpe_id: int | None,
    management_router_id: int | None,
    category: AlertCategory,
    severity: Severity,
    title: str,
    description: str,
    is_prediction: bool = False,
    confidence: int | None = None,
    llm_explanation: str | None = None,
    notify: bool = True,
    settings: EffectiveSettings | None = None,
) -> Alert:
    query = select(Alert).where(Alert.category == category, Alert.status != AlertStatus.resolved)
    query = query.where(Alert.cpe_id == cpe_id) if cpe_id is not None else query.where(Alert.management_router_id == management_router_id)
    existing = (await db.execute(query)).scalar_one_or_none()

    if existing:
        escalated = _SEVERITY_RANK[severity] > _SEVERITY_RANK[existing.severity]
        existing.severity = severity
        existing.title = title
        existing.description = description
        existing.is_prediction = is_prediction
        existing.confidence = confidence
        if llm_explanation:
            existing.llm_explanation = llm_explanation
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        if notify and escalated and severity == Severity.critical:
            eff = settings or await get_effective(db)
            await notify_alert(title, description, severity.value, eff)
        return existing

    alert = Alert(
        cpe_id=cpe_id,
        management_router_id=management_router_id,
        category=category,
        severity=severity,
        title=title,
        description=description,
        is_prediction=is_prediction,
        confidence=confidence,
        llm_explanation=llm_explanation,
        status=AlertStatus.open,
    )
    db.add(alert)
    if notify and severity == Severity.critical:
        eff = settings or await get_effective(db)
        await notify_alert(title, description, severity.value, eff)
    return alert


async def resolve_alert(db: AsyncSession, *, cpe_id: int | None, management_router_id: int | None, category: AlertCategory) -> None:
    query = select(Alert).where(Alert.category == category, Alert.status != AlertStatus.resolved)
    query = query.where(Alert.cpe_id == cpe_id) if cpe_id is not None else query.where(Alert.management_router_id == management_router_id)
    existing = (await db.execute(query)).scalar_one_or_none()
    if existing:
        existing.status = AlertStatus.resolved
        existing.resolved_at = datetime.now(timezone.utc)
        db.add(existing)
