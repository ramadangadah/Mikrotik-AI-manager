from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.alert import AlertCategory, AlertStatus, Severity


class AlertOut(BaseModel):
    id: int
    cpe_id: int | None
    management_router_id: int | None
    severity: Severity
    category: AlertCategory
    title: str
    description: str
    llm_explanation: str | None
    is_prediction: bool
    confidence: int | None
    status: AlertStatus
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}
