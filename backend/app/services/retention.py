"""
Keeps the metrics table from growing forever. Raw (per-poll) samples older
than METRIC_RETENTION_DAYS are collapsed into hourly averages; hourly rows
older than METRIC_ROLLUP_RETENTION_DAYS are dropped entirely. This runs once
a day and is the main reason the app stays "light" even after months of
polling thousands of devices.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.cpe import CPE
from app.models.metric import Granularity, MetricSample

logger = logging.getLogger(__name__)
settings = get_settings()


def _hour_bucket(ts: datetime) -> datetime:
    return ts.replace(minute=0, second=0, microsecond=0)


async def _rollup_cpe(db: AsyncSession, cpe_id: int, cutoff: datetime) -> int:
    result = await db.execute(
        select(MetricSample).where(
            MetricSample.cpe_id == cpe_id,
            MetricSample.granularity == Granularity.raw,
            MetricSample.timestamp < cutoff,
        )
    )
    rows = result.scalars().all()
    if not rows:
        return 0

    buckets: dict[tuple, list[float]] = defaultdict(list)
    for row in rows:
        key = (row.metric_type, row.interface_name, _hour_bucket(row.timestamp))
        buckets[key].append(row.value)

    for (metric_type, iface, hour), values in buckets.items():
        avg = sum(values) / len(values)
        db.add(
            MetricSample(
                cpe_id=cpe_id,
                metric_type=metric_type,
                granularity=Granularity.hourly,
                value=round(avg, 3),
                interface_name=iface,
                timestamp=hour,
            )
        )

    ids = [row.id for row in rows]
    await db.execute(delete(MetricSample).where(MetricSample.id.in_(ids)))
    return len(rows)


async def run_retention_job() -> dict:
    raw_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.METRIC_RETENTION_DAYS)
    rollup_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.METRIC_ROLLUP_RETENTION_DAYS)

    total_collapsed = 0
    async with AsyncSessionLocal() as db:
        cpe_ids = (await db.execute(select(CPE.id))).scalars().all()
        for cpe_id in cpe_ids:
            total_collapsed += await _rollup_cpe(db, cpe_id, raw_cutoff)
        await db.commit()

        result = await db.execute(
            delete(MetricSample).where(
                MetricSample.granularity == Granularity.hourly,
                MetricSample.timestamp < rollup_cutoff,
            )
        )
        await db.commit()

    logger.info("retention job: collapsed %d raw samples, pruned old rollups", total_collapsed)
    return {"raw_samples_collapsed": total_collapsed}
