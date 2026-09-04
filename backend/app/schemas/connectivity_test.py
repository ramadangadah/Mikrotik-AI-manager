from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.connectivity_test import TestMethod


class ConnectivityTestRun(BaseModel):
    method: TestMethod = TestMethod.ip


class ConnectivityTestManualUpdate(BaseModel):
    rebooted: bool | None = None
    tplink_speedtest_notes: str | None = None
    client_pc_speedtest_notes: str | None = None
    notes: str | None = None


class ConnectivityTestOut(BaseModel):
    id: int
    cpe_id: int
    method: TestMethod
    performed_by: str | None
    run_error: str | None

    sector_name: str | None
    registered: bool | None
    snr_db: float | None
    signal_dbm: float | None
    vh_ratio_db: float | None
    cpe_uptime_seconds: int | None
    bts_connection_seconds: int | None
    cpe_firmware: str | None
    bts_firmware: str | None
    firmware_aligned: bool | None
    disconnect_count: int | None
    disconnect_window_days: int
    ethernet_link_speed: str | None

    ping_gateway_target: str | None
    ping_gateway_result: str | None
    ping_public_ip_target: str | None
    ping_public_ip_result: str | None
    ping_domain_target: str | None
    ping_domain_result: str | None
    bandwidth_test_result: str | None

    rebooted: bool
    tplink_speedtest_notes: str | None
    client_pc_speedtest_notes: str | None
    notes: str | None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
