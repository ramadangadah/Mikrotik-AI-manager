from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.management_router import ApiType, DeviceStatus


class ConnectionMode(str, enum.Enum):
    direct = "direct"                # app -> CPE directly over the LAN/WAN
    socks_relay = "socks_relay"      # app -> mgmt router SOCKS proxy -> CPE
    vpn_tunnel = "vpn_tunnel"        # app -> PPTP/L2TP tunnel into mgmt router's LAN -> CPE (routed like "direct")
    unmanaged = "unmanaged"          # discovered only, no credentials yet


class DeviceType(str, enum.Enum):
    mikrotik_routeros = "mikrotik_routeros"
    generic_snmp = "generic_snmp"
    unknown = "unknown"


class CPE(Base):
    """
    A managed endpoint: an outdoor antenna, a client-side MikroTik router, or
    any other RouterOS device sitting under a ManagementRouter. Some CPEs run
    PPPoE client and therefore have their own internet/route out; others run
    in pure bridge mode with only a local management IP (or none at all),
    reachable solely through the management router's network.
    """

    __tablename__ = "cpes"

    id: Mapped[int] = mapped_column(primary_key=True)
    network_id: Mapped[int] = mapped_column(ForeignKey("networks.id", ondelete="CASCADE"))
    management_router_id: Mapped[int] = mapped_column(ForeignKey("management_routers.id", ondelete="CASCADE"))

    name: Mapped[str] = mapped_column(String(128))
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)  # mgmt IP, may be None if L2-only
    mac_address: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    port: Mapped[int] = mapped_column(Integer, default=443)
    api_type: Mapped[ApiType] = mapped_column(default=ApiType.rest)
    device_type: Mapped[DeviceType] = mapped_column(default=DeviceType.mikrotik_routeros)
    connection_mode: Mapped[ConnectionMode] = mapped_column(default=ConnectionMode.unmanaged)

    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    password_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)

    bridge_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    has_internet: Mapped[bool] = mapped_column(Boolean, default=False)
    pppoe_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    pppoe_username: Mapped[str | None] = mapped_column(String(128), nullable=True)

    role: Mapped[str | None] = mapped_column(String(32), nullable=True)  # "antenna" | "router" | "ap" | ...
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    routeros_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[DeviceStatus] = mapped_column(default=DeviceStatus.unknown)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    uptime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Latest snapshot values, updated by the poller, for cheap dashboard reads
    # without hitting the metrics table.
    last_cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_signal_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ccq_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ping_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    monitored: Mapped[bool] = mapped_column(Boolean, default=True)  # poller skips if False

    # If True, the moment this CPE flips from offline back to online (e.g. it
    # was factory-reset or swapped for a spare unit in the field), the app
    # automatically pushes its most recent config_backups row back onto it
    # via /system/backup/load - restoring it to its last known-good config
    # without anyone having to notice and click "restore" by hand.
    auto_restore_on_reconnect: Mapped[bool] = mapped_column(Boolean, default=False)
    last_restore_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    network: Mapped["Network"] = relationship(back_populates="cpes")  # noqa: F821
