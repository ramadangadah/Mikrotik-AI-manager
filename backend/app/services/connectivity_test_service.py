"""
Runs the field-technician "client connectivity test" checklist against a
CPE - the radio checks (registered to sector, SNR, signal, V/H chain
balance, uptime, BTS link time, firmware match, disconnect count, ethernet
link speed) and the network tests (ping to the PPPoE gateway / 8.8.8.8 / a
public domain, and RouterOS's own /tool bandwidth-test toward an internal
speed-test server) - either over the CPE's normal IP connection or, when
asked, over MAC-Telnet by MAC address (see mactelnet_service.py).

What CAN'T be pulled from the device at all - power-cycling the PoE
injector, a TP-Link router's own speed-test page, a client PC's fast.com
result - is deliberately left null on the ConnectivityTest row for a
technician to fill in afterwards via PATCH /api/connectivity-tests/{id}.
A field RouterOS simply doesn't expose for a given driver/model (not every
wireless chipset reports signal-to-noise or per-chain signal, for example)
is also left null rather than guessed at - shown as "-" in the UI.

Design note on how results get pulled:
  - Over IP, RouterOS's REST/binary API has no notion of "run this command
    and stream me output" (see script_service.py's own docstring on this) -
    so ping and bandwidth-test both go through the same
    save-script/run/read-log trick script_service.py already uses for
    ad-hoc commands, using RouterOS's `as-value` ping option to get
    structured sent/received/rtt numbers back through the log.
  - Over MAC-Telnet, we DO get a real interactive terminal (that's the
    whole point of MAC-Telnet), so we just run the exact commands a
    technician would type and capture their normal text output directly -
    including /tool bandwidth-test's live table, which is quite literally
    what "incollare i risultati" (paste the results) means on the original
    paper checklist.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertCategory
from app.models.connectivity_test import ConnectivityTest, TestMethod
from app.models.cpe import CPE
from app.models.management_router import ManagementRouter
from app.services import mactelnet_service
from app.services.device_connect import target_for_cpe
from app.services.polling_service import _parse_uptime
from app.services.routeros_client import RouterOSError, connect
from app.services.script_service import run_script

logger = logging.getLogger(__name__)

DISCONNECT_WINDOW_DAYS = 7


# --- shared field extraction (works on both the API's JSON dict and the
# MAC-Telnet terminal's parsed "key: value" text) -----------------------

def _get(kv: dict, *keys: str) -> str | None:
    for k in keys:
        if k in kv and kv[k] not in (None, ""):
            return str(kv[k])
    return None


def _as_float(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", v))
    except ValueError:
        return None


def _extract_radio_fields(kv: dict) -> dict:
    signal = _as_float(_get(kv, "signal-strength", "rx-signal"))
    ch0 = _as_float(_get(kv, "signal-strength-ch0", "rx-signal-strength-ch0"))
    ch1 = _as_float(_get(kv, "signal-strength-ch1", "rx-signal-strength-ch1"))
    noise = _as_float(_get(kv, "noise-floor"))
    snr = _as_float(_get(kv, "signal-to-noise"))
    if snr is None and signal is not None and noise is not None:
        snr = round(signal - noise, 1)
    vh = None
    if ch0 is not None and ch1 is not None:
        vh = round(abs(ch0 - ch1), 1)

    status = (_get(kv, "status") or "").lower()
    registered = None
    if status:
        registered = status in ("connected", "running", "true", "yes")
    elif signal is not None:
        registered = True

    return {
        "sector_name": _get(kv, "ssid", "current-ap", "interface"),
        "registered": registered,
        "signal_dbm": signal,
        "snr_db": snr,
        "vh_ratio_db": vh,
        "ccq": _as_float(_get(kv, "tx-ccq")),
    }


def _parse_terminal_kv(text: str) -> dict:
    """RouterOS terminal `print`/`monitor` output is one "key: value" pair
    per line (with a leading label column sometimes) - pull out whatever
    key/value pairs are there, tolerant of the extra whitespace/columns."""
    kv: dict[str, str] = {}
    for line in (text or "").splitlines():
        m = re.match(r"^\s*([a-zA-Z][a-zA-Z0-9_-]*)\s*:\s*(.+?)\s*$", line)
        if m:
            kv[m.group(1).lower()] = m.group(2)
    return kv


PING_SUMMARY_LINE_RE = re.compile(r"sent=\s*\d+.*?received=\s*\d+.*?packet-loss=\s*[\d.]+%.*", re.IGNORECASE)


def _extract_ping_summary(text: str) -> str | None:
    for line in (text or "").splitlines():
        if PING_SUMMARY_LINE_RE.search(line):
            return line.strip()
    return None


# --- IP path -------------------------------------------------------------

def _ping_script(tag: str, address: str, count: int) -> str:
    return (
        f':do {{\n'
        f'  :local res [/ping address="{address}" count={count} as-value]\n'
        f'  :local last ($res->($[:len $res]-1))\n'
        f'  :log info ("{tag} sent=" . ($last->"sent") . " received=" . ($last->"received") . '
        f'" packet-loss=" . ($last->"packet-loss") . "% avg-rtt=" . ($last->"avg-rtt"))\n'
        f'}} on-error={{ :log info ("{tag} FAILED") }}\n'
    )


def _bandwidth_script(target: str, username: str, password: str, duration_s: int) -> str:
    return (
        f':do {{\n'
        f'  :local res [/tool bandwidth-test address="{target}" user="{username}" password="{password}" '
        f'protocol=tcp duration={duration_s}s direction=both as-value]\n'
        f'  :local last ($res->($[:len $res]-1))\n'
        f'  :log info ("CTBW " . $last)\n'
        f'}} on-error={{ :log info ("CTBW FAILED - check target/credentials/reachability") }}\n'
    )


async def _run_via_ip(cpe: CPE, router: ManagementRouter, eff) -> dict:
    target = target_for_cpe(cpe, router)
    data: dict = {}

    async with connect(target) as ros:
        resource = await ros.get_single("system/resource")
        data["cpe_firmware"] = resource.get("version")
        try:
            data["cpe_uptime_seconds"] = _parse_uptime(resource.get("uptime"))
        except Exception:
            pass

        wireless: list[dict] = []
        try:
            wireless = await ros.list("interface/wireless/registration-table")
        except RouterOSError:
            pass
        if not wireless:
            try:
                wireless = await ros.list("interface/wireless/monitor")
            except RouterOSError:
                pass
        if wireless:
            radio = _extract_radio_fields(wireless[0])
            data.update({k: v for k, v in radio.items() if k != "ccq"})

        eth_speed = None
        try:
            eth = await ros.list("interface/ethernet/monitor")
            if eth:
                eth_speed = eth[0].get("rate")
        except RouterOSError:
            pass
        data["ethernet_link_speed"] = eth_speed

        gateway = None
        try:
            routes = await ros.list("ip/route")
            default = next((r for r in routes if r.get("dst-address") in ("0.0.0.0/0", "0.0.0.0")), None)
            gateway = (default or {}).get("gateway")
        except RouterOSError:
            pass
        data["ping_gateway_target"] = gateway

    # Ping(s) + bandwidth-test, bundled into one throwaway script so it's
    # one extra connection instead of up to four.
    count = eff.ping_test_count
    parts = []
    if gateway:
        parts.append(_ping_script("CTPING_GW", gateway, count))
    parts.append(_ping_script("CTPING_PUB", "8.8.8.8", count))
    data["ping_domain_target"] = eff.ping_test_domain
    if eff.ping_test_domain:
        parts.append(_ping_script("CTPING_DOM", eff.ping_test_domain, count))
    data["ping_public_ip_target"] = "8.8.8.8"
    if eff.bandwidth_test_target and cpe.device_type.value == "mikrotik_routeros":
        parts.append(_bandwidth_script(
            eff.bandwidth_test_target, eff.bandwidth_test_username, eff.bandwidth_test_password,
            eff.bandwidth_test_duration_seconds,
        ))

    if parts:
        try:
            result = await run_script(target, "\n".join(parts))
            tail = result.get("log_tail", "")
            data["ping_gateway_result"] = _log_line_for(tail, "CTPING_GW")
            data["ping_public_ip_result"] = _log_line_for(tail, "CTPING_PUB")
            data["ping_domain_result"] = _log_line_for(tail, "CTPING_DOM")
            data["bandwidth_test_result"] = _log_line_for(tail, "CTBW")
        except RouterOSError as e:
            logger.info("connectivity test ping/bandwidth script failed for cpe %s: %s", cpe.id, e)

    return data


def _log_line_for(tail: str, tag: str) -> str | None:
    for line in (tail or "").splitlines():
        if tag in line:
            # log lines look like "<time> [<topics>] <tag> <rest>"
            idx = line.find(tag)
            return line[idx + len(tag):].strip(' :"')
    return None


# --- MAC-Telnet path -------------------------------------------------------

async def _run_via_mactelnet(cpe: CPE, eff) -> dict:
    if not cpe.mac_address:
        raise ValueError("This CPE has no MAC address on file - run discovery via the router's tables first")
    if not cpe.username:
        raise ValueError("Set a username/password on this CPE first")

    from app.core.crypto import decrypt

    password = decrypt(cpe.password_encrypted) if cpe.password_encrypted else ""

    commands = [
        "/system resource print",
        "/interface wireless monitor [/interface wireless find] once",
        "/interface ethernet monitor [/interface ethernet find] once",
        "/ip route print where dst-address=0.0.0.0/0",
        f"/ping 8.8.8.8 count={eff.ping_test_count}",
    ]
    if eff.ping_test_domain:
        commands.append(f"/ping {eff.ping_test_domain} count={eff.ping_test_count}")
    if eff.bandwidth_test_target and cpe.device_type.value == "mikrotik_routeros":
        commands.append(
            f"/tool bandwidth-test address={eff.bandwidth_test_target} user={eff.bandwidth_test_username} "
            f"password={eff.bandwidth_test_password} protocol=tcp duration={eff.bandwidth_test_duration_seconds}s"
        )

    out = await mactelnet_service.run_commands(cpe.mac_address, cpe.username, password, commands)

    data: dict = {}
    resource_kv = _parse_terminal_kv(out.get("/system resource print", ""))
    data["cpe_firmware"] = resource_kv.get("version")
    try:
        data["cpe_uptime_seconds"] = _parse_uptime(resource_kv.get("uptime"))
    except Exception:
        pass

    wireless_kv = _parse_terminal_kv(out.get("/interface wireless monitor [/interface wireless find] once", ""))
    if wireless_kv:
        radio = _extract_radio_fields(wireless_kv)
        data.update({k: v for k, v in radio.items() if k != "ccq"})

    eth_kv = _parse_terminal_kv(out.get("/interface ethernet monitor [/interface ethernet find] once", ""))
    data["ethernet_link_speed"] = eth_kv.get("rate")

    route_kv = _parse_terminal_kv(out.get("/ip route print where dst-address=0.0.0.0/0", ""))
    gateway = route_kv.get("gateway")
    data["ping_gateway_target"] = gateway
    data["ping_public_ip_target"] = "8.8.8.8"
    data["ping_domain_target"] = eff.ping_test_domain

    data["ping_public_ip_result"] = _extract_ping_summary(out.get(f"/ping 8.8.8.8 count={eff.ping_test_count}", ""))
    if eff.ping_test_domain:
        data["ping_domain_result"] = _extract_ping_summary(
            out.get(f"/ping {eff.ping_test_domain} count={eff.ping_test_count}", "")
        )
    bw_key = (
        f"/tool bandwidth-test address={eff.bandwidth_test_target} user={eff.bandwidth_test_username} "
        f"password={eff.bandwidth_test_password} protocol=tcp duration={eff.bandwidth_test_duration_seconds}s"
    )
    if bw_key in out:
        data["bandwidth_test_result"] = out[bw_key].strip() or None

    # MAC-Telnet gives us a console, not the router's own route table for a
    # ping to the gateway from THIS session context - reuse the same
    # ping-script idea isn't available here, so ping the gateway too if we
    # found one.
    if gateway:
        gw_out = await mactelnet_service.run_commands(
            cpe.mac_address, cpe.username, password, [f"/ping {gateway} count={eff.ping_test_count}"]
        )
        data["ping_gateway_result"] = _extract_ping_summary(gw_out.get(f"/ping {gateway} count={eff.ping_test_count}", ""))

    return data


# --- public entrypoint -----------------------------------------------------

async def run_test(db: AsyncSession, cpe: CPE, method: TestMethod, performed_by: str | None, eff) -> ConnectivityTest:
    router = await db.get(ManagementRouter, cpe.management_router_id)

    test = ConnectivityTest(cpe_id=cpe.id, method=method, performed_by=performed_by)
    try:
        if method == TestMethod.mac_telnet:
            data = await _run_via_mactelnet(cpe, eff)
        else:
            if not cpe.host:
                raise ValueError("This CPE has no IP address on file - use the MAC-Telnet method instead")
            data = await _run_via_ip(cpe, router, eff)
        for k, v in data.items():
            if hasattr(test, k) and v is not None:
                setattr(test, k, v)
    except (RouterOSError, mactelnet_service.MacTelnetError, ValueError) as e:
        test.run_error = str(e)[:500]

    # Firmware alignment against the tower (management router) - independent
    # of which path we used to reach the CPE.
    if router and router.routeros_version:
        test.bts_firmware = router.routeros_version
        if test.cpe_firmware:
            test.firmware_aligned = test.cpe_firmware == router.routeros_version

    # Disconnect count over the trailing window, from this app's own alert
    # history - RouterOS itself doesn't keep a "times this device dropped"
    # counter, but we do, from every offline-transition alert we've raised.
    since = datetime.now(timezone.utc) - timedelta(days=DISCONNECT_WINDOW_DAYS)
    count = (
        await db.execute(
            select(func.count(Alert.id)).where(
                Alert.cpe_id == cpe.id, Alert.category == AlertCategory.offline, Alert.created_at >= since
            )
        )
    ).scalar_one()
    test.disconnect_count = count
    test.disconnect_window_days = DISCONNECT_WINDOW_DAYS

    db.add(test)
    await db.commit()
    await db.refresh(test)
    return test
