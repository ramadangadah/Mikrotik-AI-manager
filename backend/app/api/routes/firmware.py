from __future__ import annotations

import hashlib
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.config import get_settings
from app.core.database import get_db
from app.models.cpe import CPE
from app.models.firmware import FirmwareFile
from app.models.job import Job, JobStatus, JobType, TargetType
from app.models.user import User
from app.schemas.job import FirmwareOut, FirmwarePushRequest, JobOut
from app.services import audit
from app.services.firmware_service import push_firmware
from app.services.job_runner import launch

router = APIRouter(prefix="/api/firmware", tags=["firmware"], dependencies=[Depends(require_password_set)])
settings = get_settings()


@router.get("", response_model=list[FirmwareOut])
async def list_firmware(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FirmwareFile).order_by(FirmwareFile.uploaded_at.desc()))
    return result.scalars().all()


@router.post("/upload", response_model=FirmwareOut, status_code=status.HTTP_201_CREATED)
async def upload_firmware(
    file: UploadFile,
    version: str | None = None,
    architecture: str | None = None,
    notes: str | None = None,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename.endswith(".npk"):
        raise HTTPException(status_code=400, detail="Firmware file must be a RouterOS .npk package")

    os.makedirs(settings.FIRMWARE_DIR, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}-{file.filename}"
    stored_path = os.path.join(settings.FIRMWARE_DIR, stored_name)

    hasher = hashlib.sha256()
    with open(stored_path, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            hasher.update(chunk)
            out.write(chunk)

    fw = FirmwareFile(
        filename=file.filename,
        stored_path=stored_path,
        version=version,
        architecture=architecture,
        notes=notes,
        sha256=hasher.hexdigest(),
    )
    db.add(fw)
    await audit.record(db, user.username, "firmware_uploaded", target=file.filename, commit=False)
    await db.commit()
    await db.refresh(fw)
    return fw


@router.delete("/{firmware_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_firmware(firmware_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    fw = await db.get(FirmwareFile, firmware_id)
    if not fw:
        raise HTTPException(status_code=404, detail="Firmware file not found")
    if os.path.exists(fw.stored_path):
        os.remove(fw.stored_path)
    await db.delete(fw)
    await audit.record(db, user.username, "firmware_deleted", target=fw.filename, commit=False)
    await db.commit()


@router.post("/push", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def push(payload: FirmwarePushRequest, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    cpe = await db.get(CPE, payload.cpe_id)
    fw = await db.get(FirmwareFile, payload.firmware_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    if not fw:
        raise HTTPException(status_code=404, detail="Firmware file not found")
    if not cpe.host or cpe.connection_mode.value == "unmanaged":
        raise HTTPException(status_code=400, detail="CPE has no credentials/host set - adopt it first")

    job = Job(job_type=JobType.firmware_upgrade, target_type=TargetType.cpe, target_id=cpe.id, status=JobStatus.pending, created_by=user.username)
    db.add(job)
    await audit.record(db, user.username, "firmware_push_started", target=cpe.name, details=fw.filename, commit=False)
    await db.commit()
    await db.refresh(job)

    launch(push_firmware(job.id, cpe.id, fw.id, ssh_port=payload.ssh_port))
    return job
