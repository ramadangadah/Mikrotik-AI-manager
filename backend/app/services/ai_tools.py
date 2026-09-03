"""
The tool surface the AI assistant is allowed to call.

Everything here except `propose_script_run` is read-only: search/list
helpers over the same DB rows the dashboard shows. The assistant can call
those freely and as many times as it needs while it figures out what the
user is asking about.

`propose_script_run` is different on purpose - it does not touch a device.
Calling it just packages up a suggested RouterOS script + target selection
in the exact shape POST /api/scripts/run expects, and ends the assistant's
turn. Nothing runs until a human looks at that proposal and confirms it
through that normal, audited endpoint. The assistant is never given a tool
that executes a script directly - that boundary is enforced by this file
simply not defining one, not by a prompt instruction the model could ignore.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.cpe import CPE
from app.models.management_router import ManagementRouter
from app.models.network import Network

TOOL_DEFS = [
    {
        "name": "search_cpes",
        "description": (
            "Search/list CPEs (antennas/routers) by name substring and/or filter by network, "
            "management router, status (online/offline/unknown), or role. Returns up to 50 matches "
            "with their id, name, status, signal, cpu/memory, and connection info. Use this first "
            "whenever the user refers to a device by name - you need its id for other tools/actions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive substring match on the CPE name"},
                "network_id": {"type": "integer"},
                "management_router_id": {"type": "integer"},
                "status": {"type": "string", "enum": ["online", "offline", "unknown"]},
            },
        },
    },
    {
        "name": "get_cpe_detail",
        "description": "Get full detail for one CPE by id: connection info, latest metrics, and its recent alerts.",
        "parameters": {
            "type": "object",
            "properties": {"cpe_id": {"type": "integer"}},
            "required": ["cpe_id"],
        },
    },
    {
        "name": "list_alerts",
        "description": "List recent alerts, optionally filtered by severity and/or open-only.",
        "parameters": {
            "type": "object",
            "properties": {
                "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                "open_only": {"type": "boolean", "description": "If true, only alerts not yet resolved. Default true."},
                "limit": {"type": "integer", "description": "Max rows, default 25, max 100."},
            },
        },
    },
    {
        "name": "list_management_routers",
        "description": "List every management router configured in the system, with id, name, host, and status.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "list_networks",
        "description": "List networks, optionally filtered to one management router, with their CPE counts.",
        "parameters": {
            "type": "object",
            "properties": {"management_router_id": {"type": "integer"}},
        },
    },
    {
        "name": "propose_script_run",
        "description": (
            "Propose running a RouterOS script on one or more devices. This does NOT execute anything - it "
            "shows the user exactly what you want to run and on what, and they must explicitly confirm it "
            "before it happens. Always use this instead of claiming you ran something. Set exactly one "
            "targeting field: cpe_id (one device), cpe_ids (an explicit list), management_router_id (run on "
            "a management router itself, not its CPEs), network_id (every monitored CPE in a network), "
            "all_cpes_under_router_id (every monitored CPE under a management router), or all_monitored_cpes "
            "(true = every monitored CPE in the whole system - use only when the user clearly asked for "
            "'all' devices)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "The RouterOS script body to run"},
                "explanation": {"type": "string", "description": "One sentence: what this script does and why, for the user"},
                "cpe_id": {"type": "integer"},
                "cpe_ids": {"type": "array", "items": {"type": "integer"}},
                "management_router_id": {"type": "integer"},
                "network_id": {"type": "integer"},
                "all_cpes_under_router_id": {"type": "integer"},
                "all_monitored_cpes": {"type": "boolean"},
            },
            "required": ["source", "explanation"],
        },
    },
]

# Anthropic wants {"input_schema": ...}; OpenAI wants {"parameters": ...} inside a "function" wrapper.
# ai_assistant_service.py adapts TOOL_DEFS to each provider's shape at call time.

READ_ONLY_TOOL_NAMES = {t["name"] for t in TOOL_DEFS if t["name"] != "propose_script_run"}


def _cpe_summary(c: CPE) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "host": c.host,
        "role": c.role,
        "status": c.status.value if c.status else None,
        "connection_mode": c.connection_mode.value if c.connection_mode else None,
        "network_id": c.network_id,
        "management_router_id": c.management_router_id,
        "monitored": c.monitored,
        "auto_restore_on_reconnect": c.auto_restore_on_reconnect,
        "last_cpu_percent": c.last_cpu_percent,
        "last_memory_percent": c.last_memory_percent,
        "last_signal_dbm": c.last_signal_dbm,
        "last_ccq_percent": c.last_ccq_percent,
        "last_ping_ms": c.last_ping_ms,
        "last_seen": c.last_seen.isoformat() if c.last_seen else None,
        "last_error": c.last_error,
    }


async def search_cpes(
    db: AsyncSession,
    query: str | None = None,
    network_id: int | None = None,
    management_router_id: int | None = None,
    status: str | None = None,
) -> list[dict]:
    stmt = select(CPE)
    if query:
        stmt = stmt.where(CPE.name.ilike(f"%{query}%"))
    if network_id is not None:
        stmt = stmt.where(CPE.network_id == network_id)
    if management_router_id is not None:
        stmt = stmt.where(CPE.management_router_id == management_router_id)
    if status:
        stmt = stmt.where(CPE.status == status)
    stmt = stmt.order_by(CPE.name).limit(50)
    rows = (await db.execute(stmt)).scalars().all()
    return [_cpe_summary(c) for c in rows]


async def get_cpe_detail(db: AsyncSession, cpe_id: int) -> dict:
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        return {"error": f"No CPE with id {cpe_id}"}
    alerts_result = await db.execute(
        select(Alert).where(Alert.cpe_id == cpe_id).order_by(Alert.created_at.desc()).limit(10)
    )
    alerts = alerts_result.scalars().all()
    detail = _cpe_summary(cpe)
    detail["model"] = cpe.model
    detail["routeros_version"] = cpe.routeros_version
    detail["uptime_seconds"] = cpe.uptime_seconds
    detail["bridge_mode"] = cpe.bridge_mode
    detail["pppoe_enabled"] = cpe.pppoe_enabled
    detail["recent_alerts"] = [
        {
            "id": a.id,
            "severity": a.severity.value,
            "category": a.category.value,
            "title": a.title,
            "status": a.status.value,
            "is_prediction": a.is_prediction,
            "created_at": a.created_at.isoformat(),
        }
        for a in alerts
    ]
    return detail


async def list_alerts(db: AsyncSession, severity: str | None = None, open_only: bool = True, limit: int = 25) -> list[dict]:
    stmt = select(Alert)
    if severity:
        stmt = stmt.where(Alert.severity == severity)
    if open_only:
        stmt = stmt.where(Alert.status != "resolved")
    stmt = stmt.order_by(Alert.created_at.desc()).limit(min(max(limit, 1), 100))
    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": a.id,
            "cpe_id": a.cpe_id,
            "management_router_id": a.management_router_id,
            "severity": a.severity.value,
            "category": a.category.value,
            "title": a.title,
            "description": a.description,
            "status": a.status.value,
            "is_prediction": a.is_prediction,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


async def list_management_routers(db: AsyncSession) -> list[dict]:
    rows = (await db.execute(select(ManagementRouter).order_by(ManagementRouter.name))).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "host": r.host,
            "status": r.status.value if r.status else None,
            "vpn_type": r.vpn_type.value if r.vpn_type else "none",
            "vpn_status": r.vpn_status.value if r.vpn_status else None,
        }
        for r in rows
    ]


async def list_networks(db: AsyncSession, management_router_id: int | None = None) -> list[dict]:
    stmt = select(Network)
    if management_router_id is not None:
        stmt = stmt.where(Network.management_router_id == management_router_id)
    rows = (await db.execute(stmt.order_by(Network.name))).scalars().all()
    out = []
    for n in rows:
        count_result = await db.execute(select(CPE.id).where(CPE.network_id == n.id))
        out.append({
            "id": n.id,
            "name": n.name,
            "management_router_id": n.management_router_id,
            "cidr": n.cidr,
            "cpe_count": len(count_result.all()),
        })
    return out


async def dispatch_read_only_tool(db: AsyncSession, name: str, args: dict) -> dict | list:
    if name == "search_cpes":
        return await search_cpes(db, **args)
    if name == "get_cpe_detail":
        return await get_cpe_detail(db, **args)
    if name == "list_alerts":
        return await list_alerts(db, **args)
    if name == "list_management_routers":
        return await list_management_routers(db)
    if name == "list_networks":
        return await list_networks(db, **args)
    return {"error": f"unknown tool {name}"}
