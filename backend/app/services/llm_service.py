"""
Optional layer that turns a rule-based finding into a plain-language
explanation + recommendation using an LLM the user brings their own key for.
Entirely optional (off by default) and never on the critical path - if it
fails or isn't configured, alerts still work with just the rule-based
description.
"""
from __future__ import annotations

import logging

from app.services.runtime_settings import EffectiveSettings

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "You are a senior wireless ISP network engineer. You are given raw facts about a "
    "MikroTik RouterOS device (an antenna/CPE or router). Write a short, plain-language "
    "explanation of what is likely happening and a concrete next action for a field "
    "technician. Be specific (mention cable, alignment, interference, overload, hardware "
    "wear, etc. only when the facts support it). Maximum 3 sentences. No markdown."
)


async def explain(context: dict, settings: EffectiveSettings) -> str | None:
    if not settings.enable_llm_explanations or not settings.llm_api_key or settings.llm_provider == "none":
        return None

    prompt = (
        f"Device: {context.get('device_name')} ({context.get('role', 'device')})\n"
        f"Category: {context.get('category')}\n"
        f"Severity: {context.get('severity')}\n"
        f"Facts: {context.get('facts')}\n"
        f"Rule-based finding: {context.get('rule_description')}\n"
    )

    try:
        if settings.llm_provider == "openai":
            return await _explain_openai(prompt, settings)
        if settings.llm_provider == "anthropic":
            return await _explain_anthropic(prompt, settings)
    except Exception as e:  # pragma: no cover - best-effort, never block alerting
        logger.warning("LLM explanation failed: %s", e)
        return None
    return None


async def _explain_openai(prompt: str, settings: EffectiveSettings) -> str | None:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.llm_api_key)
    resp = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=200,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip() if resp.choices else None


async def _explain_anthropic(prompt: str, settings: EffectiveSettings) -> str | None:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.llm_api_key)
    model = settings.llm_model if "claude" in settings.llm_model else "claude-3-5-haiku-latest"
    resp = await client.messages.create(
        model=model,
        max_tokens=200,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "\n".join(parts).strip() if parts else None
