"""
Optional outbound notifications for new/escalated critical alerts. Both
channels are off unless configured; failures are logged and swallowed so a
bad webhook URL never breaks alert processing.
"""
from __future__ import annotations

import logging

import httpx

from app.services.runtime_settings import EffectiveSettings

logger = logging.getLogger(__name__)


async def notify_alert(title: str, description: str, severity: str, settings: EffectiveSettings) -> None:
    async with httpx.AsyncClient(timeout=8) as client:
        if settings.notify_webhook_url:
            try:
                await client.post(settings.notify_webhook_url, json={"title": title, "description": description, "severity": severity})
            except Exception as e:
                logger.warning("webhook notification failed: %s", e)

        if settings.notify_telegram_bot_token and settings.notify_telegram_chat_id:
            try:
                url = f"https://api.telegram.org/bot{settings.notify_telegram_bot_token}/sendMessage"
                text = f"[{severity.upper()}] {title}\n{description}"
                await client.post(url, json={"chat_id": settings.notify_telegram_chat_id, "text": text})
            except Exception as e:
                logger.warning("telegram notification failed: %s", e)
