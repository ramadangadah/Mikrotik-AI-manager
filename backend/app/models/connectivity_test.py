from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TestMethod(str, enum.Enum):
    ip = "ip"                  # reached over the CPE's normal IP path (direct/socks_relay/vpn_tunnel)
    mac_telnet = "mac_telnet"  # reached over MikroTik MAC-Telnet by MAC address


class ConnectivityTest(Base):
    """
    One run of the field-technician "client connectivity test" checklist
    against a CPE - the radio checks and network tests a technician would
    otherwise fill in by hand on a paper/spreadsheet form. Whatever RouterOS
    exposes is pulled automatically (via IP or MAC-Telnet - see
    services/connectivity_test_service.py); the handful of items that can't
    be automated (power-cycling the PoE injector, a TP-Link router's own
    speed test, a client PC's fast.com result) are left null here until a
    technician fills them in via PATCH /api/connectivity-tests/{id}.

    A field left null after the automated run means RouterOS simply didn't
    report it for that device/driver - shown as "-" in the UI rather than a
    guess.
    """

    __tablename__ = "connectivity_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    cpe_id: Mapped[int] = mapped_column(ForeignKey("cpes.id", ondelete="CASCADE"), index=True)

    method: Mapped[TestMethod] = mapped_column(default=TestMethod.ip)
    performed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    run_error: Mapped[str | None] = mapped_column(String(512), nullable=True)  # set if the automated run itself couldn't connect at all

    # --- CONTROLLI SULLA RADIO DEL CLIENTE (radio checks) ---
    sector_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    registered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    snr_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    vh_ratio_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpe_uptime_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bts_connection_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpe_firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bts_firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)
    firmware_aligned: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    disconnect_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disconnect_window_days: Mapped[int] = mapped_column(Integer, default=7)
    ethernet_link_speed: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # --- TEST DI RETE (network tests) ---
    ping_gateway_target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ping_gateway_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    ping_public_ip_target: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ping_public_ip_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    ping_domain_target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ping_domain_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    bandwidth_test_result: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Manual entries (technician fills these in afterwards) ---
    rebooted: Mapped[bool] = mapped_column(Boolean, default=False)
    tplink_speedtest_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_pc_speedtest_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    cpe: Mapped["CPE"] = relationship()  # noqa: F821
