from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.cpe import ConnectionMode, DeviceType
from app.models.management_router import ApiType, DeviceStatus


class CPECreate(BaseModel):
    network_id: int
    name: str = Field(min_length=1, max_length=128)
    host: str | None = None
    mac_address: str | None = None
    port: int = 443
    api_type: ApiType = ApiType.rest
    device_type: DeviceType = DeviceType.mikrotik_routeros
    connection_mode: ConnectionMode = ConnectionMode.unmanaged
    username: str | None = None
    password: str | None = None
    bridge_mode: bool = False
    role: str | None = "antenna"
    monitored: bool = True
    auto_restore_on_reconnect: bool = False


class CPEUpdate(BaseModel):
    name: str | None = None
    network_id: int | None = None
    host: str | None = None
    port: int | None = None
    api_type: ApiType | None = None
    connection_mode: ConnectionMode | None = None
    username: str | None = None
    password: str | None = None
    bridge_mode: bool | None = None
    role: str | None = None
    monitored: bool | None = None
    auto_restore_on_reconnect: bool | None = None


class BulkAdoptRequest(BaseModel):
    cpe_ids: list[int]
    username: str
    password: str
    connection_mode: ConnectionMode = ConnectionMode.socks_relay
    api_type: ApiType = ApiType.rest


class CPEOut(BaseModel):
    id: int
    network_id: int
    management_router_id: int
    name: str
    host: str | None
    mac_address: str | None
    port: int
    api_type: ApiType
    device_type: DeviceType
    connection_mode: ConnectionMode
    username: str | None
    bridge_mode: bool
    has_internet: bool
    pppoe_enabled: bool
    pppoe_username: str | None
    role: str | None
    model: str | None
    routeros_version: str | None
    status: DeviceStatus
    last_seen: datetime | None
    last_error: str | None
    uptime_seconds: int | None
    last_cpu_percent: float | None
    last_memory_percent: float | None
    last_signal_dbm: float | None
    last_ccq_percent: float | None
    last_ping_ms: float | None
    monitored: bool
    auto_restore_on_reconnect: bool
    last_restore_job_id: int | None

    model_config = {"from_attributes": True}
