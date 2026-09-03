from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.app_setting import AppSetting

_BOOL_TRUE = {"1", "true", "yes", "on"}


@dataclass
class EffectiveSettings:
    enable_llm_explanations: bool
    llm_provider: str
    llm_api_key: str | None
    llm_model: str
    enable_ml_anomaly_detection: bool
    notify_webhook_url: str | None
    notify_telegram_bot_token: str | None
    notify_telegram_chat_id: str | None


EDITABLE_KEYS = [
    "enable_llm_explanations",
    "llm_provider",
    "llm_api_key",
    "llm_model",
    "enable_ml_anomaly_detection",
    "notify_webhook_url",
    "notify_telegram_bot_token",
    "notify_telegram_chat_id",
]


async def get_overrides(db: AsyncSession) -> dict[str, str | None]:
    rows = (await db.execute(select(AppSetting))).scalars().all()
    return {r.key: r.value for r in rows}


async def get_effective(db: AsyncSession) -> EffectiveSettings:
    base = get_settings()
    overrides = await get_overrides(db)

    def pick(key: str, default):
        return overrides[key] if key in overrides and overrides[key] is not None else default

    def pick_bool(key: str, default: bool) -> bool:
        raw = overrides.get(key)
        if raw is None:
            return default
        return raw.lower() in _BOOL_TRUE

    return EffectiveSettings(
        enable_llm_explanations=pick_bool("enable_llm_explanations", base.ENABLE_LLM_EXPLANATIONS),
        llm_provider=pick("llm_provider", base.LLM_PROVIDER),
        llm_api_key=pick("llm_api_key", base.LLM_API_KEY),
        llm_model=pick("llm_model", base.LLM_MODEL),
        enable_ml_anomaly_detection=pick_bool("enable_ml_anomaly_detection", base.ENABLE_ML_ANOMALY_DETECTION),
        notify_webhook_url=pick("notify_webhook_url", base.NOTIFY_WEBHOOK_URL),
        notify_telegram_bot_token=pick("notify_telegram_bot_token", base.NOTIFY_TELEGRAM_BOT_TOKEN),
        notify_telegram_chat_id=pick("notify_telegram_chat_id", base.NOTIFY_TELEGRAM_CHAT_ID),
    )


async def set_values(db: AsyncSession, values: dict[str, str | None]) -> None:
    for key, value in values.items():
        if key not in EDITABLE_KEYS:
            continue
        existing = await db.get(AppSetting, key)
        if existing:
            existing.value = value
            db.add(existing)
        else:
            db.add(AppSetting(key=key, value=value))
    await db.commit()
