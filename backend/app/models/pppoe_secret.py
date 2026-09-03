from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PPPoESecret(Base):
    """
    A cached, encrypted copy of a `/ppp secret` entry pulled from a router
    that acts as a PPPoE server (often the management router itself, or a
    dedicated BRAS). This is a convenience backup so you're not locked out of
    your own customer credential list if a router dies - not a source of
    truth; the router remains authoritative.
    """

    __tablename__ = "pppoe_secrets"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_router_id: Mapped[int] = mapped_column(ForeignKey("management_routers.id", ondelete="CASCADE"))

    username: Mapped[str] = mapped_column(String(128), index=True)
    password_encrypted: Mapped[str] = mapped_column(String(512))
    profile: Mapped[str | None] = mapped_column(String(128), nullable=True)
    service: Mapped[str | None] = mapped_column(String(32), nullable=True)
    caller_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    remote_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    comment: Mapped[str | None] = mapped_column(String(255), nullable=True)

    last_synced_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
