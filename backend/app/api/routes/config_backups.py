from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.config_backup import BackupTargetType, ConfigBackup
from app.models.cpe import CPE
from app.models.management_router import ManagementRouter
from app.models.user import User
from app.schemas.job import JobOut
from app.services import audit
from app.services.config_backup_service import backup_cpe, backup_management_router, restore_now
from app.services.routeros_client import RouterOSError

router = APIRouter(prefix="/api/config-backups", tags=["config-backups"], dependencies=[Depends(require_password_set)])


class BackupOut(BaseModel):
    id: int
    target_type: BackupTargetType
    target_id: int
    target_name: str
    size_bytes: int | None
    routeros_version: str | None
    created_at: str

    model_config = {"from_attributes": True}


@router.get("")
async def list_backups(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ConfigBackup).order_by(ConfigBackup.created_at.desc()).limit(200))
    return [
        {
            "id": b.id,
            "target_type": b.target_type,
            "target_id": b.target_id,
            "target_name": b.target_name,
            "size_bytes": b.size_bytes,
            "routeros_version": b.routeros_version,
            "created_at": b.created_at.isoformat(),
        }
        for b in result.scalars().all()
    ]


@router.post("/management-router/{router_id}")
async def backup_router_now(
    router_id: int,
    ssh_port: int = 22,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    try:
        backup = await backup_management_router(db, mr, ssh_port=ssh_port)
    except (RouterOSError, OSError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    await audit.record(db, user.username, "config_backup_created", target=mr.name)
    return {"id": backup.id, "stored_path": backup.stored_path}


@router.post("/cpe/{cpe_id}")
async def backup_cpe_now(
    cpe_id: int,
    ssh_port: int = 22,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    router_row = await db.get(ManagementRouter, cpe.management_router_id)
    try:
        backup = await backup_cpe(db, cpe, router_row, ssh_port=ssh_port)
    except (RouterOSError, OSError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    await audit.record(db, user.username, "config_backup_created", target=cpe.name)
    return {"id": backup.id, "stored_path": backup.stored_path}


@router.get("/{backup_id}/download")
async def download_backup(backup_id: int, db: AsyncSession = Depends(get_db)):
    backup = await db.get(ConfigBackup, backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(backup.stored_path, filename=f"{backup.target_name}-{backup.created_at.date()}.backup")


@router.post("/{backup_id}/restore", response_model=JobOut, status_code=202)
async def restore_backup(
    backup_id: int,
    ssh_port: int = 22,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Pushes this stored backup back onto the device it came from and tells
    RouterOS to load it - restoring that exact config (the device reboots on
    its own to apply it). Use this to manually put a CPE back to a known-good
    config; for it to happen automatically the moment a swapped/reset device
    reappears online, turn on "auto restore on reconnect" for that CPE
    instead (PATCH /api/cpes/{id} with auto_restore_on_reconnect=true) -
    that path calls this same restore logic on its own.
    """
    backup = await db.get(ConfigBackup, backup_id)
    if not backup:
        raise HTTPException(status_code=404, detail="Backup not found")
    if not os.path.exists(backup.stored_path):
        raise HTTPException(status_code=410, detail="Backup file is no longer on disk")

    if backup.target_type == BackupTargetType.cpe:
        target_row = await db.get(CPE, backup.target_id)
    else:
        target_row = await db.get(ManagementRouter, backup.target_id)
    if not target_row:
        raise HTTPException(status_code=404, detail=f"The {backup.target_type.value} this backup was taken from no longer exists")

    job = await restore_now(db, backup, ssh_port=ssh_port, created_by=user.username)
    await audit.record(db, user.username, "config_restore_started", target=backup.target_name, details=f"backup #{backup.id}")
    return job
