from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.management_router import ApiType, DeviceStatus, VpnStatus, VpnType


class ManagementRouterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    host: str
    port: int = 443
    api_type: ApiType = ApiType.rest
    username: str
    password: str
    verify_tls: bool = False
    discovery_cidr: str | None = None
    use_socks_relay: bool = True
    socks_port: int = 1080
    vpn_type: VpnType = VpnType.none
    vpn_server: str | None = None
    vpn_username: str | None = None
    vpn_password: str | None = None
    vpn_local_cidr: str | None = None
    # WireGuard-only
    wg_peer_public_key: str | None = None
    wg_preshared_key: str | None = None
    wg_endpoint_port: int = 51820
    wg_local_address: str | None = None
    wg_keepalive: int = 25


class ManagementRouterUpdate(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    api_type: ApiType | None = None
    username: str | None = None
    password: str | None = None
    verify_tls: bool | None = None
    discovery_cidr: str | None = None
    use_socks_relay: bool | None = None
    socks_port: int | None = None
    vpn_type: VpnType | None = None
    vpn_server: str | None = None
    vpn_username: str | None = None
    vpn_password: str | None = None
    vpn_local_cidr: str | None = None
    wg_peer_public_key: str | None = None
    wg_preshared_key: str | None = None
    wg_endpoint_port: int | None = None
    wg_local_address: str | None = None
    wg_keepalive: int | None = None


class ManagementRouterOut(BaseModel):
    id: int
    name: str
    host: str
    port: int
    api_type: ApiType
    username: str
    verify_tls: bool
    discovery_cidr: str | None
    use_socks_relay: bool
    socks_port: int
    vpn_type: VpnType
    vpn_server: str | None
    vpn_username: str | None
    vpn_local_cidr: str | None
    vpn_status: VpnStatus
    vpn_interface: str | None
    vpn_last_error: str | None
    vpn_connected_at: datetime | None
    wg_public_key: str | None
    wg_peer_public_key: str | None
    wg_endpoint_port: int
    wg_local_address: str | None
    wg_keepalive: int
    identity: str | None
    routeros_version: str | None
    board_name: str | None
    status: DeviceStatus
    last_seen: datetime | None
    last_error: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
