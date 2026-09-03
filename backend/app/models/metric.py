from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MetricType(str, enum.Enum):
    cpu_percent = "cpu_percent"
    memory_percent = "memory_percent"
    disk_percent = "disk_percent"
    signal_dbm = "signal_dbm"
    ccq_percent = "ccq_percent"
    tx_rate_bps = "tx_rate_bps"
    rx_rate_bps = "rx_rate_bps"
    interface_errors = "interface_errors"          # rx/tx CRC + drops, summed
    ping_latency_ms = "ping_latency_ms"
    ping_loss_percent = "ping_loss_percent"
    pppoe_online = "pppoe_online"                   # 1/0
    voltage = "voltage"
    temperature = "temperature"


class Granularity(str, enum.Enum):
    raw = "raw"
    hourly = "hourly"


class MetricSample(Base):
    __tablename__ = "metric_samples"
    __table_args__ = (
        Index("ix_metric_cpe_type_time", "cpe_id", "metric_type", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cpe_id: Mapped[int] = mapped_column(ForeignKey("cpes.id", ondelete="CASCADE"))
    metric_type: Mapped[MetricType] = mapped_column(Enum(MetricType))
    granularity: Mapped[Granularity] = mapped_column(Enum(Granularity), default=Granularity.raw)
    value: Mapped[float] = mapped_column(Float)
    interface_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
