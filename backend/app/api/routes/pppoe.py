from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_password_set
from app.core.database import get_db
from app.models.management_router import ManagementRouter
from app.models.pppoe_secret import PPPoESecret
from app.models.user import User
from app.services import audit
from app.services.pppoe_backup_service import export_csv, sync_pppoe_secrets
from app.services.routeros_client import RouterOSError

router = APIRouter(prefix="/api/pppoe", tags=["pppoe"], dependencies=[Depends(require_password_set)])


class SecretOut(BaseModel):
    id: int
    source_router_id: int
    username: str
    profile: str | None
    service: str | None
    disabled: bool
    comment: str | None

    model_config = {"from_attributes": True}


@router.get("/secrets", response_model=list[SecretOut])
async def list_secrets(source_router_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(PPPoESecret)
    if source_router_id:
        query = query.where(PPPoESecret.source_router_id == source_router_id)
    result = await db.execute(query.order_by(PPPoESecret.username))
    return result.scalars().all()


@router.post("/sync/{router_id}")
async def sync_secrets(router_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    try:
        summary = await sync_pppoe_secrets(db, mr)
    except RouterOSError as e:
        raise HTTPException(status_code=502, detail=str(e))
    await audit.record(db, user.username, "pppoe_secrets_synced", target=mr.name, details=str(summary))
    return summary


@router.get("/export", response_class=PlainTextResponse)
async def export_secrets(source_router_id: int | None = None, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    """
    Downloads the encrypted-at-rest PPPoE secret backup as plaintext CSV.
    Admin-only and audited - this is your customer credential list.
    """
    csv_text = await export_csv(db, source_router_id)
    await audit.record(db, user.username, "pppoe_secrets_exported", target=str(source_router_id or "all"))
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pppoe_secrets_backup.csv"},
    )
