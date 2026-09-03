from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_password_set
from app.core.database import get_db
from app.models.job import Job
from app.schemas.job import JobOut

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(require_password_set)])


@router.get("", response_model=list[JobOut])
async def list_jobs(limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Job).order_by(Job.created_at.desc()).limit(limit))
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
