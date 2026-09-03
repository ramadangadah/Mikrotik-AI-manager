"""
The AI assistant's chat loop: natural language in, either a plain answer or
a proposed action out. Reuses the same LLM provider/key/model already
configured for alert explanations (Settings page) - if none is configured,
the assistant is simply unavailable and the route says so.

How tool use is bounded, on purpose:
  - The model can call any of the read-only tools in ai_tools.py as many
    times as it wants within one request (search devices, pull alert
    history, etc.) - that's just it looking things up, same as a person
    clicking around the dashboard.
  - The ONLY way it can suggest changing anything is `propose_script_run`,
    which doesn't touch a device - it just returns a structured proposal
    matching POST /api/scripts/run's request shape. This service always
    stops and returns that proposal to the caller rather than acting on it.
    Nothing runs until a human reviews it and calls that endpoint
    themselves (or the frontend's "confirm and run" button does, on their
    explicit click) - the assistant is never given a tool that executes.

Conversation memory here is intentionally simple: the caller passes prior
turns as plain {role, content} text pairs (no tool-call bookkeeping crosses
a request boundary), and this module runs its own bounded tool loop fresh
each request. That's enough for "what did I just ask" continuity without
needing to persist provider-specific message formats.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai_tools import READ_ONLY_TOOL_NAMES, TOOL_DEFS, dispatch_read_only_tool
from app.services.runtime_settings import EffectiveSettings

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 6

SYSTEM_PROMPT = (
    "You are the network operations assistant embedded in a MikroTik RouterOS fleet-management "
    "app for a wireless ISP. You can look up CPEs (antennas/client routers), management routers, "
    "networks, and alerts using your tools - use them rather than guessing, and use search_cpes "
    "before assuming you know a device's id. "
    "You can NOT execute anything directly. If the user asks you to run a command, change a "
    "setting, restart something, or create/run a RouterOS script on one or more devices, call "
    "propose_script_run with the exact script and target selection - never claim you ran it or "
    "that it's done. The user will see your proposal and must explicitly confirm before anything "
    "happens on real hardware. "
    "Keep answers concise and concrete: device names/ids, numbers, and next actions rather than "
    "generic advice. If you're not sure which device(s) the user means, ask, or search first."
)


class AssistantUnavailableError(Exception):
    pass


def _openai_tools() -> list[dict]:
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
        for t in TOOL_DEFS
    ]


def _anthropic_tools() -> list[dict]:
    return [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOL_DEFS]


async def chat(db: AsyncSession, message: str, history: list[dict], settings: EffectiveSettings) -> dict:
    """
    Returns {"reply": str, "proposed_action": dict | None}.
    `history` is a list of {"role": "user"|"assistant", "content": str}, oldest first.
    """
    if settings.llm_provider == "none" or not settings.llm_api_key:
        raise AssistantUnavailableError(
            "No LLM provider is configured. Set an LLM provider and API key on the Settings page first."
        )

    if settings.llm_provider == "openai":
        return await _chat_openai(db, message, history, settings)
    if settings.llm_provider == "anthropic":
        return await _chat_anthropic(db, message, history, settings)
    raise AssistantUnavailableError(f"Unsupported LLM provider: {settings.llm_provider}")


async def _chat_openai(db: AsyncSession, message: str, history: list[dict], settings: EffectiveSettings) -> dict:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.llm_api_key)
    tools = _openai_tools()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = await client.chat.completions.create(
            model=settings.llm_model, messages=messages, tools=tools, tool_choice="auto", max_tokens=800, temperature=0.2,
        )
        choice = resp.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            return {"reply": msg.content or "", "proposed_action": None}

        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        })

        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "propose_script_run":
                return {"reply": args.get("explanation", "Here's what I'd like to run:"), "proposed_action": args}

            if name in READ_ONLY_TOOL_NAMES:
                try:
                    result = await dispatch_read_only_tool(db, name, args)
                except Exception as e:  # a bad tool call shouldn't kill the whole conversation
                    logger.warning("assistant tool %s failed: %s", name, e)
                    result = {"error": str(e)}
            else:
                result = {"error": f"unknown tool {name}"}

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)})

    return {"reply": "I wasn't able to finish looking into that within my tool-call budget - try narrowing the question.", "proposed_action": None}


async def _chat_anthropic(db: AsyncSession, message: str, history: list[dict], settings: EffectiveSettings) -> dict:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.llm_api_key)
    model = settings.llm_model if "claude" in settings.llm_model else "claude-3-5-sonnet-latest"
    tools = _anthropic_tools()

    messages = [{"role": turn["role"], "content": turn["content"]} for turn in history]
    messages.append({"role": "user", "content": message})

    for _ in range(MAX_TOOL_ITERATIONS):
        resp = await client.messages.create(
            model=model, max_tokens=800, system=SYSTEM_PROMPT, messages=messages, tools=tools,
        )

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]

        if not tool_uses:
            return {"reply": "\n".join(text_parts).strip(), "proposed_action": None}

        for block in tool_uses:
            if block.name == "propose_script_run":
                args = block.input
                return {"reply": args.get("explanation", "Here's what I'd like to run:"), "proposed_action": args}

        messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})

        tool_results = []
        for block in tool_uses:
            if block.name in READ_ONLY_TOOL_NAMES:
                try:
                    result = await dispatch_read_only_tool(db, block.name, block.input)
                except Exception as e:
                    logger.warning("assistant tool %s failed: %s", block.name, e)
                    result = {"error": str(e)}
            else:
                result = {"error": f"unknown tool {block.name}"}
            tool_results.append({
                "type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result, default=str),
            })
        messages.append({"role": "user", "content": tool_results})

    return {"reply": "I wasn't able to finish looking into that within my tool-call budget - try narrowing the question.", "proposed_action": None}
