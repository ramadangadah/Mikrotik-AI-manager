from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RouterRoute(Base):
    """
    A private network (CIDR) reachable through a specific management
    router's tunnel, plus what it's for. Replaces a single hardcoded
    "remote LAN CIDR" per router: a site's VPN tunnel commonly needs to
    carry several distinct subnets at once (the towers' own management
    VLAN, a customer-facing CPE range, a separate PPPoE pool, etc.), and a
    technician should be able to see at a glance which management router
    is the path to a given private range.

    When a PPTP/L2TP/WireGuard tunnel to management_router comes up, every
    CIDR registered here is added as a route through that tunnel interface
    (see services/vpn_service.py); when it goes down, they're removed
    again. For WireGuard this becomes the peer's AllowedIPs list.
    """

    __tablename__ = "router_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    management_router_id: Mapped[int] = mapped_column(
        ForeignKey("management_routers.id", ondelete="CASCADE"), index=True
    )
    cidr: Mapped[str] = mapped_column(String(64))  # e.g. "10.20.30.0/24"
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    management_router: Mapped["ManagementRouter"] = relationship(back_populates="routes")  # noqa: F821
