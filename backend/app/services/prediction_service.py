"""
The "AI" in this app is two layered pieces, both explainable (never a black
box you have to trust blindly):

  1. Rule-based thresholds on the latest snapshot - fast, deterministic,
     runs every poll cycle. Catches "this is a problem right now".
  2. Trend + anomaly analysis on recent history - runs on a slower schedule.
     Catches "this is heading toward a problem" (predictive alerts) and
     "this doesn't look like this device's normal behaviour" (ML anomaly
     detection via IsolationForest), even when no fixed threshold is
     crossed yet.

Both layers can optionally be handed off to an LLM (see llm_service.py) to
turn the raw finding into a plain-language explanation + recommendation.
That step is pure narration on top of numbers we already trust - the LLM is
never the thing deciding whether an alert fires.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.ml.anomaly import detect_anomaly
from app.ml.trend import linear_trend
from app.models.alert import AlertCategory, Severity
from app.models.cpe import CPE
from app.models.management_router import DeviceStatus
from app.models.metric import MetricSample, MetricType
from app.services import llm_service
from app.services.alert_service import resolve_alert, upsert_alert
from app.services.runtime_settings import EffectiveSettings, get_effective

logger = logging.getLogger(__name__)
base_settings = get_settings()

# --- thresholds (tune to your network; see README) ---
CPU_WARN, CPU_CRIT = 80.0, 95.0
MEM_WARN, MEM_CRIT = 85.0, 95.0
SIGNAL_WARN, SIGNAL_CRIT = -75.0, -85.0   # dBm - more negative is weaker
CCQ_WARN, CCQ_CRIT = 70.0, 50.0           # % - lower is worse
PING_WARN_MS, PING_CRIT_MS = 300.0, 1200.0
INTERFACE_ERROR_RATE_WARN = 50.0          # errors/hour, from trend slope

TREND_WINDOW_HOURS = 12
PREDICTION_HORIZON_HOURS = 7 * 24  # only alert if trouble is projected within a week


async def _maybe_llm(cpe: CPE, category: AlertCategory, severity: Severity, description: str, facts: dict, eff: EffectiveSettings) -> str | None:
    if not eff.enable_llm_explanations:
        return None
    return await llm_service.explain(
        {
            "device_name": cpe.name,
            "role": cpe.role,
            "category": category.value,
            "severity": severity.value,
            "facts": facts,
            "rule_description": description,
        },
        eff,
    )


async def evaluate_current_state(db: AsyncSession) -> int:
    """Threshold checks against the latest polled snapshot. Cheap, runs every cycle."""
    eff = await get_effective(db)
    cpes = (await db.execute(select(CPE).where(CPE.monitored.is_(True)))).scalars().all()
    alerts_touched = 0

    for cpe in cpes:
        if cpe.status == DeviceStatus.offline:
            await upsert_alert(
                db,
                cpe_id=cpe.id,
                management_router_id=None,
                category=AlertCategory.offline,
                severity=Severity.critical,
                title=f"{cpe.name} is offline",
                description=(cpe.last_error or "Device stopped responding to polling.")[:400],
                settings=eff,
            )
            alerts_touched += 1
            # Don't bother evaluating other metrics for an unreachable device.
            continue
        else:
            await resolve_alert(db, cpe_id=cpe.id, management_router_id=None, category=AlertCategory.offline)

        await _check_threshold(
            db, cpe, cpe.last_cpu_percent, CPU_WARN, CPU_CRIT, higher_is_worse=True,
            category=AlertCategory.cpu, label="CPU load", unit="%", eff=eff,
        )
        await _check_threshold(
            db, cpe, cpe.last_memory_percent, MEM_WARN, MEM_CRIT, higher_is_worse=True,
            category=AlertCategory.memory, label="Memory usage", unit="%", eff=eff,
        )
        if cpe.last_signal_dbm is not None:
            await _check_threshold(
                db, cpe, cpe.last_signal_dbm, SIGNAL_WARN, SIGNAL_CRIT, higher_is_worse=False,
                category=AlertCategory.signal, label="Wireless signal", unit="dBm", eff=eff,
            )
        if cpe.last_ccq_percent is not None:
            await _check_threshold(
                db, cpe, cpe.last_ccq_percent, CCQ_WARN, CCQ_CRIT, higher_is_worse=False,
                category=AlertCategory.wifi, label="Connection quality (CCQ)", unit="%", eff=eff,
            )
        if cpe.last_ping_ms is not None:
            await _check_threshold(
                db, cpe, cpe.last_ping_ms, PING_WARN_MS, PING_CRIT_MS, higher_is_worse=True,
                category=AlertCategory.cable, label="API round-trip latency", unit="ms", eff=eff,
            )
        alerts_touched += 1

    await db.commit()
    return alerts_touched


async def _check_threshold(db, cpe: CPE, value, warn, crit, *, higher_is_worse: bool, category: AlertCategory, label: str, unit: str, eff: EffectiveSettings):
    if value is None:
        return

    def worse(a, b):
        return a > b if higher_is_worse else a < b

    if worse(value, crit):
        severity = Severity.critical
    elif worse(value, warn):
        severity = Severity.warning
    else:
        await resolve_alert(db, cpe_id=cpe.id, management_router_id=None, category=category)
        return

    description = f"{label} is {value:.1f}{unit} on {cpe.name}."
    llm_text = await _maybe_llm(cpe, category, severity, description, {"value": value, "unit": unit, "warn": warn, "crit": crit}, eff)
    await upsert_alert(
        db,
        cpe_id=cpe.id,
        management_router_id=None,
        category=category,
        severity=severity,
        title=f"{label} {'high' if higher_is_worse else 'low'} on {cpe.name}",
        description=description,
        llm_explanation=llm_text,
        settings=eff,
    )


async def evaluate_trends_and_anomalies(db: AsyncSession) -> int:
    """Slower-cadence pass: trend-based predictions + optional ML anomaly detection."""
    eff = await get_effective(db)
    cpes = (await db.execute(select(CPE).where(CPE.monitored.is_(True)))).scalars().all()
    since = datetime.now(timezone.utc) - timedelta(hours=TREND_WINDOW_HOURS)
    touched = 0

    trend_targets = [
        (MetricType.signal_dbm, SIGNAL_CRIT, False, AlertCategory.signal, "Wireless signal", "dBm"),
        (MetricType.cpu_percent, CPU_CRIT, True, AlertCategory.cpu, "CPU load", "%"),
        (MetricType.memory_percent, MEM_CRIT, True, AlertCategory.memory, "Memory usage", "%"),
    ]

    for cpe in cpes:
        for metric_type, crit, higher_is_worse, category, label, unit in trend_targets:
            result = await db.execute(
                select(MetricSample.timestamp, MetricSample.value).where(
                    MetricSample.cpe_id == cpe.id,
                    MetricSample.metric_type == metric_type,
                    MetricSample.timestamp >= since,
                ).order_by(MetricSample.timestamp)
            )
            rows = result.all()
            points = [(r.timestamp, r.value) for r in rows]
            trend = linear_trend(points)
            if not trend or trend.r_squared < 0.4:
                continue  # not a clean enough trend to project

            degrading = (trend.slope_per_hour > 0) == higher_is_worse
            if not degrading:
                continue

            hours_to_crit = trend.hours_until(crit)
            if hours_to_crit is None or hours_to_crit > PREDICTION_HORIZON_HOURS:
                continue

            days = hours_to_crit / 24
            confidence = int(min(95, max(30, trend.r_squared * 100)))
            description = (
                f"{label} on {cpe.name} has moved from ~{trend.current_value - trend.slope_per_hour * trend.n_points:.1f}"
                f" to {trend.current_value:.1f}{unit} over the last {TREND_WINDOW_HOURS}h "
                f"({trend.slope_per_hour:+.2f}{unit}/hour). At this rate it will likely cross the critical "
                f"threshold ({crit}{unit}) in about {days:.1f} day(s)."
            )
            llm_text = await _maybe_llm(
                cpe, category, Severity.warning, description,
                {"slope_per_hour": trend.slope_per_hour, "days_to_critical": round(days, 1), "r_squared": trend.r_squared},
                eff,
            )
            await upsert_alert(
                db,
                cpe_id=cpe.id,
                management_router_id=None,
                category=category,
                severity=Severity.warning,
                title=f"Predicted: {label} degrading on {cpe.name}",
                description=description,
                is_prediction=True,
                confidence=confidence,
                llm_explanation=llm_text,
                notify=False,
                settings=eff,
            )
            touched += 1

        if eff.enable_ml_anomaly_detection:
            touched += await _run_anomaly_checks(db, cpe, eff)

    await db.commit()
    return touched


async def _run_anomaly_checks(db: AsyncSession, cpe: CPE, eff: EffectiveSettings) -> int:
    touched = 0
    for metric_type in (MetricType.cpu_percent, MetricType.memory_percent, MetricType.interface_errors, MetricType.ping_latency_ms):
        result = await db.execute(
            select(MetricSample.value)
            .where(MetricSample.cpe_id == cpe.id, MetricSample.metric_type == metric_type)
            .order_by(MetricSample.timestamp.desc())
            .limit(base_settings.ML_MIN_SAMPLES + 1)
        )
        values = [r[0] for r in result.all()]
        if len(values) < base_settings.ML_MIN_SAMPLES:
            continue

        latest, history = values[0], values[1:]
        is_anomalous, score = detect_anomaly(history, latest)
        if is_anomalous and score > 0.55:
            description = (
                f"{metric_type.value} on {cpe.name} ({latest:.1f}) looks unusual compared to this device's "
                f"own recent history, even though it hasn't crossed a fixed threshold."
            )
            await upsert_alert(
                db,
                cpe_id=cpe.id,
                management_router_id=None,
                category=AlertCategory.generic_anomaly,
                severity=Severity.info,
                title=f"Unusual {metric_type.value.replace('_', ' ')} on {cpe.name}",
                description=description,
                is_prediction=True,
                confidence=int(min(90, score * 100)),
                notify=False,
                settings=eff,
            )
            touched += 1
    return touched


async def run_prediction_cycle(full: bool = False) -> dict:
    async with AsyncSessionLocal() as db:
        current = await evaluate_current_state(db)
        trend_count = 0
        if full:
            trend_count = await evaluate_trends_and_anomalies(db)
    return {"current_state_checked": current, "trend_anomaly_checked": trend_count}
