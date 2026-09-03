"""
Wires the background jobs. One AsyncIOScheduler instance for the whole app -
started from main.py's lifespan handler, stopped cleanly on shutdown.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.management_router import ManagementRouter
from app.services.discovery_service import run_discovery
from app.services.polling_service import polling_engine
from app.services.prediction_service import run_prediction_cycle
from app.services.retention import run_retention_job

logger = logging.getLogger(__name__)
settings = get_settings()

scheduler = AsyncIOScheduler()


async def _job_poll_and_check_now():
    try:
        result = await polling_engine.poll_all_once()
        await run_prediction_cycle(full=False)
        logger.info("poll cycle: %s", result)
    except Exception:
        logger.exception("poll cycle failed")


async def _job_full_prediction_pass():
    try:
        result = await run_prediction_cycle(full=True)
        logger.info("prediction (trend/ML) pass: %s", result)
    except Exception:
        logger.exception("prediction pass failed")


async def _job_auto_discovery():
    try:
        async with AsyncSessionLocal() as db:
            routers = (
                await db.execute(select(ManagementRouter).where(ManagementRouter.discovery_cidr.is_not(None)))
            ).scalars().all()
            for router in routers:
                try:
                    summary = await run_discovery(db, router)
                    logger.info("auto-discovery on %s: %s", router.name, summary)
                except Exception:
                    logger.exception("auto-discovery failed for router %s", router.name)
    except Exception:
        logger.exception("auto-discovery job failed")


async def _job_retention():
    try:
        await run_retention_job()
    except Exception:
        logger.exception("retention job failed")


def start_scheduler() -> None:
    scheduler.add_job(
        _job_poll_and_check_now, IntervalTrigger(seconds=settings.POLL_INTERVAL_FAST_SECONDS),
        id="poll_and_check", max_instances=1, coalesce=True, misfire_grace_time=60,
    )
    scheduler.add_job(
        _job_full_prediction_pass, IntervalTrigger(seconds=settings.ML_RETRAIN_INTERVAL_SECONDS),
        id="full_prediction_pass", max_instances=1, coalesce=True, misfire_grace_time=120,
    )
    scheduler.add_job(
        _job_auto_discovery, IntervalTrigger(seconds=settings.DISCOVERY_INTERVAL_SECONDS),
        id="auto_discovery", max_instances=1, coalesce=True, misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_retention, IntervalTrigger(hours=24),
        id="retention", max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("scheduler started (poll=%ss, prediction=%ss, discovery=%ss)",
                settings.POLL_INTERVAL_FAST_SECONDS, settings.ML_RETRAIN_INTERVAL_SECONDS, settings.DISCOVERY_INTERVAL_SECONDS)


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
