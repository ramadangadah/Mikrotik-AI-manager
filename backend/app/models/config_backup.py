from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BackupTargetType(str, enum.Enum):
    management_router = "management_router"
    cpe = "cpe"


class ConfigBackup(Base):
    """A timestamped copy of a device's `/system/backup/save` output, pulled via SFTP."""

    __tablename__ = "config_backups"

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[BackupTargetType] = mapped_column(Enum(BackupTargetType))
    target_id: Mapped[int] = mapped_column(Integer)
    target_name: Mapped[str] = mapped_column(String(128))
    stored_path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    routeros_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
