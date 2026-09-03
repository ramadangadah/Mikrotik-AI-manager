from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.job import JobStatus, JobType, TargetType


class JobOut(BaseModel):
    id: int
    job_type: JobType
    target_type: TargetType
    target_id: int
    status: JobStatus
    progress: int
    log: str | None
    created_by: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}


class FirmwarePushRequest(BaseModel):
    cpe_id: int
    firmware_id: int
    ssh_port: int = 22


class FirmwareOut(BaseModel):
    id: int
    filename: str
    version: str | None
    architecture: str | None
    notes: str | None
    sha256: str | None
    uploaded_at: datetime

    model_config = {"from_attributes": True}
