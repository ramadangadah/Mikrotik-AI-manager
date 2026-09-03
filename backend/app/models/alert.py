from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Severity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class AlertCategory(str, enum.Enum):
    offline = "offline"
    signal = "signal"
    wifi = "wifi"
    cable = "cable"
    cpu = "cpu"
    memory = "memory"
    pppoe = "pppoe"
    throughput_anomaly = "throughput_anomaly"
    firmware = "firmware"
    generic_anomaly = "generic_anomaly"


class AlertStatus(str, enum.Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    cpe_id: Mapped[int | None] = mapped_column(ForeignKey("cpes.id", ondelete="CASCADE"), nullable=True)
    management_router_id: Mapped[int | None] = mapped_column(
        ForeignKey("management_routers.id", ondelete="CASCADE"), nullable=True
    )

    severity: Mapped[Severity] = mapped_column(Enum(Severity), default=Severity.info)
    category: Mapped[AlertCategory] = mapped_column(Enum(AlertCategory))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text)
    llm_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # True when this is a *predictive* alert ("signal trending down, likely
    # failure in ~3 days") rather than a current-state alert ("device is
    # offline right now").
    is_prediction: Mapped[bool] = mapped_column(Boolean, default=False)
    confidence: Mapped[float | None] = mapped_column(Integer, nullable=True)  # 0-100

    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.open)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
