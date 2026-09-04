from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.user import User
from app.services import audit
from app.services.runtime_settings import EDITABLE_KEYS, get_effective, set_values

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


class SettingsUpdate(BaseModel):
    enable_llm_explanations: bool | None = None
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    enable_ml_anomaly_detection: bool | None = None
    notify_webhook_url: str | None = None
    notify_telegram_bot_token: str | None = None
    notify_telegram_chat_id: str | None = None
    ping_test_domain: str | None = None
    ping_test_count: int | None = None
    bandwidth_test_target: str | None = None
    bandwidth_test_username: str | None = None
    bandwidth_test_password: str | None = None
    bandwidth_test_duration_seconds: int | None = None


@router.get("")
async def get_current_settings(db: AsyncSession = Depends(get_db)):
    eff = await get_effective(db)
    data = eff.__dict__.copy()
    if data.get("llm_api_key"):
        data["llm_api_key"] = "•" * 8 + data["llm_api_key"][-4:]
    if data.get("notify_telegram_bot_token"):
        data["notify_telegram_bot_token"] = "•" * 8 + data["notify_telegram_bot_token"][-4:]
    if data.get("bandwidth_test_password"):
        data["bandwidth_test_password"] = "•" * 8
    return data


@router.put("")
async def update_settings(payload: SettingsUpdate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    values = {k: (str(v) if not isinstance(v, str) else v) for k, v in payload.model_dump(exclude_unset=True).items() if k in EDITABLE_KEYS}
    await set_values(db, values)
    await audit.record(db, user.username, "settings_updated", details=",".join(values.keys()))
    return await get_current_settings(db)
