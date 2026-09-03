"""
Backs up PPPoE secrets (username/password/profile) from a router acting as a
PPPoE server, so you're never locked out of your own customer credential
list if that router's config is lost. This is a read-only mirror, encrypted
at rest with the same Fernet key as everything else - the router itself
always remains the source of truth.

Note: reading plaintext secret passwords via the API requires the API user
to be in the "full"/admin group on that router - RouterOS will return
'****' instead of the real password for lower-privilege accounts.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.models.management_router import ManagementRouter
from app.models.pppoe_secret import PPPoESecret
from app.services.device_connect import target_for_management_router
from app.services.routeros_client import RouterOSError, connect

logger = logging.getLogger(__name__)


async def sync_pppoe_secrets(db: AsyncSession, router: ManagementRouter) -> dict:
    target = target_for_management_router(router)
    async with connect(target) as ros:
        secrets = await ros.list("ppp/secret")

    seen_usernames = set()
    created, updated, skipped = 0, 0, 0

    for s in secrets:
        username = s.get("name")
        password = s.get("password")
        if not username:
            continue
        seen_usernames.add(username)
        if not password or password == "****":
            skipped += 1
            continue

        result = await db.execute(
            select(PPPoESecret).where(PPPoESecret.source_router_id == router.id, PPPoESecret.username == username)
        )
        existing = result.scalar_one_or_none()
        fields = dict(
            password_encrypted=encrypt(password),
            profile=s.get("profile"),
            service=s.get("service"),
            caller_id=s.get("caller-id") or None,
            local_address=s.get("local-address") or None,
            remote_address=s.get("remote-address") or None,
            disabled=str(s.get("disabled", "false")).lower() == "true",
            comment=s.get("comment"),
            last_synced_at=datetime.now(timezone.utc),
        )
        if existing:
            for k, v in fields.items():
                setattr(existing, k, v)
            db.add(existing)
            updated += 1
        else:
            db.add(PPPoESecret(source_router_id=router.id, username=username, **fields))
            created += 1

    await db.commit()
    return {"total_on_router": len(secrets), "created": created, "updated": updated, "skipped_masked": skipped}


async def export_csv(db: AsyncSession, source_router_id: int | None = None) -> str:
    """Returns CSV text with decrypted passwords. Caller is responsible for
    treating the result as sensitive (auth-gated endpoint, not logged)."""
    query = select(PPPoESecret)
    if source_router_id:
        query = query.where(PPPoESecret.source_router_id == source_router_id)
    rows = (await db.execute(query.order_by(PPPoESecret.username))).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["username", "password", "profile", "service", "caller_id", "disabled", "comment", "last_synced_at"])
    for r in rows:
        writer.writerow([
            r.username,
            decrypt(r.password_encrypted),
            r.profile or "",
            r.service or "",
            r.caller_id or "",
            r.disabled,
            r.comment or "",
            r.last_synced_at.isoformat(),
        ])
    return buf.getvalue()
