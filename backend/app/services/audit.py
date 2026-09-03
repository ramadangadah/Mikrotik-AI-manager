from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record(
    db: AsyncSession,
    username: str,
    action: str,
    target: str | None = None,
    details: str | None = None,
    ip_address: str | None = None,
    commit: bool = True,
) -> None:
    db.add(AuditLog(username=username, action=action, target=target, details=details, ip_address=ip_address))
    if commit:
        await db.commit()
