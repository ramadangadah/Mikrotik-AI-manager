from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ApiType(str, enum.Enum):
    rest = "rest"          # RouterOS 7 HTTP REST API (recommended)
    api_ssl = "api-ssl"    # binary API over TLS, port 8729
    api = "api"            # binary API, port 8728 (legacy/unencrypted)


class DeviceStatus(str, enum.Enum):
    online = "online"
    offline = "offline"
    degraded = "degraded"
    unknown = "unknown"


class VpnType(str, enum.Enum):
    none = "none"
    pptp = "pptp"
    l2tp = "l2tp"
    wireguard = "wireguard"


class VpnStatus(str, enum.Enum):
    disconnected = "disconnected"
    connecting = "connecting"
    connected = "connected"
    error = "error"


class ManagementRouter(Base):
    """
    A top-level router the app authenticates against directly. Each one owns
    one or more Networks, which in turn contain the CPEs it can see/reach.
    You can register as many ManagementRouters as you have sites.
    """

    __tablename__ = "management_routers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    host: Mapped[str] = mapped_column(String(255))               # IP or hostname
    port: Mapped[int] = mapped_column(Integer, default=443)
    api_type: Mapped[ApiType] = mapped_column(Enum(ApiType), default=ApiType.rest)
    username: Mapped[str] = mapped_column(String(128))
    password_encrypted: Mapped[str] = mapped_column(String(512))
    verify_tls: Mapped[bool] = mapped_column(Boolean, default=False)

    # Discovery scope: CIDR or range (e.g. "10.10.0.0/24") scanned for CPEs.
    discovery_cidr: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # If true, this router's built-in SOCKS proxy (IP > SOCKS) is used as a
    # relay to reach CPEs that have no direct route from the app (e.g. pure
    # bridge-mode antennas only reachable from inside that router's LAN).
    use_socks_relay: Mapped[bool] = mapped_column(Boolean, default=True)
    socks_port: Mapped[int] = mapped_column(Integer, default=1080)

    # Alternative reachability path: instead of (or alongside) the SOCKS
    # relay, dial a PPTP/L2TP VPN into this router's own LAN - the same way
    # a technician would from a laptop - so every CPE on that LAN becomes
    # reachable at the OS network-routing level, with no per-request relay
    # hop. Once connected, CPEs whose IP falls inside vpn_local_cidr are
    # reachable as "direct" without any further app-level plumbing.
    vpn_type: Mapped[VpnType] = mapped_column(Enum(VpnType), default=VpnType.none)
    vpn_server: Mapped[str | None] = mapped_column(String(255), nullable=True)  # defaults to `host` if blank
    vpn_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vpn_password_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # The remote LAN CIDR reachable once the tunnel is up, e.g. "10.10.0.0/24" -
    # a route to this network is added via the tunnel interface on connect.
    vpn_local_cidr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vpn_status: Mapped[VpnStatus] = mapped_column(Enum(VpnStatus), default=VpnStatus.disconnected)
    vpn_interface: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vpn_last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)
    vpn_connected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # WireGuard-specific config (vpn_type=wireguard). Much simpler/more
    # robust than PPTP/L2TP - a single interface, no external daemon dance -
    # and natively supported by RouterOS 7+ as a peer. `wg_local_address` is
    # the tunnel IP *this app* gets on the router's WireGuard network (the
    # "IP config" you create for the tunnel, e.g. "10.10.0.250/32"); the
    # router's own WireGuard peer public key goes in `wg_peer_public_key`.
    wg_private_key_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    wg_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)  # not secret - shown in UI to paste into RouterOS
    wg_peer_public_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wg_preshared_key_encrypted: Mapped[str | None] = mapped_column(String(512), nullable=True)
    wg_endpoint_port: Mapped[int] = mapped_column(Integer, default=51820)
    wg_local_address: Mapped[str | None] = mapped_column(String(64), nullable=True)  # e.g. "10.10.0.250/32"
    wg_keepalive: Mapped[int] = mapped_column(Integer, default=25)

    identity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    routeros_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    board_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[DeviceStatus] = mapped_column(Enum(DeviceStatus), default=DeviceStatus.unknown)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    networks: Mapped[list["Network"]] = relationship(back_populates="management_router", cascade="all, delete-orphan")  # noqa: F821
