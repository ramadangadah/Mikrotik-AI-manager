"""
Talks to a CPE over MikroTik's MAC-Telnet protocol - a raw console session
addressed by MAC address (`mactelnet <mac> -u <user> -p <password>`, the
same tool a technician runs from a laptop plugged into the antenna's own
switch/segment) instead of by IP. It's the same RouterOS terminal you'd get
over SSH/Winbox, just reached at layer 2.

Why this exists: discovery via a management router's neighbor/ARP tables
(see discovery_service.py) already captures each CPE's MAC address even
when it has no usable IP yet. This module is what makes that MAC actually
usable for something - connecting to, and running diagnostics against, a
CPE that way instead of (or in addition to) its IP.

Important limitation, stated plainly: MAC-Telnet is a layer-2 broadcast
protocol. It only works when this app has broadcast-domain (L2) reachability
to the CPE's own network segment - e.g. this app is deployed on the same
LAN/backhaul ring as your towers, or a tower bridges that segment to the app
over something like EoIP/L2TPv3. It does NOT work over the public internet,
through the SOCKS relay (that's a TCP-only relay), or across the PPTP/L2TP/
WireGuard tunnels vpn_service.py dials (those are all routed layer-3
tunnels, not layer-2 bridges). If this app runs somewhere without L2
reachability to a given CPE, MAC-Telnet to it will simply time out - use the
IP path for that device instead.

Requires the `mactelnet` client binary (apt package `mactelnet-client`,
installed in the Docker image) and drives it as an interactive terminal via
pexpect, since MAC-Telnet has no request/response API of its own - same as
SSH, it's just a shell.
"""
from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)

# RouterOS terminal prompts look like "[admin@MikroTik] > " or, mid-menu,
# "[admin@MikroTik] /interface> " - match either.
PROMPT_RE = r"\[[^\]\r\n]*\]\s*[^\r\n>]*>\s*$"
CONNECT_TIMEOUT_S = 15
DEFAULT_COMMAND_TIMEOUT_S = 45


class MacTelnetError(Exception):
    pass


def _norm_mac(mac: str) -> str:
    return mac.strip().upper().replace("-", ":")


async def run_commands(
    mac_address: str,
    username: str,
    password: str,
    commands: list[str],
    command_timeout: float = DEFAULT_COMMAND_TIMEOUT_S,
) -> dict[str, str]:
    """
    Opens one MAC-Telnet session, runs each command in `commands` in order
    (typed exactly as you would in Winbox's terminal), and returns
    {command: captured_output_text}. Always closes the session with /quit
    when done. Runs the blocking pexpect session in a worker thread so it
    doesn't block the event loop.
    """
    return await asyncio.to_thread(
        _run_commands_sync, _norm_mac(mac_address), username, password, commands, command_timeout
    )


def _run_commands_sync(
    mac_address: str, username: str, password: str, commands: list[str], command_timeout: float
) -> dict[str, str]:
    try:
        import pexpect
    except ImportError as e:
        raise MacTelnetError("pexpect is not installed in this image") from e

    args = [mac_address, "-u", username, "-p", password, "-t", str(int(CONNECT_TIMEOUT_S)), "-q"]

    try:
        child = pexpect.spawn("mactelnet", args, timeout=CONNECT_TIMEOUT_S, encoding="utf-8", codec_errors="replace")
    except pexpect.exceptions.ExceptionPexpect as e:
        raise MacTelnetError(f"could not start the mactelnet client: {e}") from e
    except FileNotFoundError as e:
        raise MacTelnetError(
            "the mactelnet client is not installed in this image (apt package mactelnet-client)"
        ) from e

    outputs: dict[str, str] = {}
    try:
        try:
            child.expect(PROMPT_RE, timeout=CONNECT_TIMEOUT_S)
        except pexpect.exceptions.TIMEOUT:
            raise MacTelnetError(
                f"no response connecting to {mac_address} over MAC-Telnet within {CONNECT_TIMEOUT_S}s - either "
                "the credentials are wrong, or this app has no layer-2 reachability to that device's network "
                "segment (MAC-Telnet does not route over the internet, the SOCKS relay, or a VPN tunnel)."
            )
        except pexpect.exceptions.EOF:
            raise MacTelnetError(
                f"MAC-Telnet session to {mac_address} closed immediately - most likely wrong username/password."
            )

        for cmd in commands:
            child.sendline(cmd)
            try:
                child.expect(PROMPT_RE, timeout=command_timeout)
                raw = child.before or ""
            except pexpect.exceptions.TIMEOUT:
                raw = (child.before or "") + "\n[command timed out after {}s]".format(int(command_timeout))
            except pexpect.exceptions.EOF:
                raw = (child.before or "") + "\n[session closed unexpectedly]"
                outputs[cmd] = _strip_echo(raw, cmd)
                break
            outputs[cmd] = _strip_echo(raw, cmd)

        try:
            child.sendline("/quit")
        except Exception:
            pass
    finally:
        try:
            if child.isalive():
                child.close(force=True)
        except Exception:
            pass

    return outputs


def _strip_echo(raw: str, cmd: str) -> str:
    """The terminal echoes back the command we just typed as the first
    line - drop it so callers just get the command's actual output."""
    lines = raw.replace("\r", "").splitlines()
    if lines and cmd.strip() and cmd.strip() in lines[0]:
        lines = lines[1:]
    return "\n".join(lines).strip()


async def test_reachable(mac_address: str, username: str, password: str) -> dict:
    """Quick reachability probe used by the CPE detail page's 'Test via
    MAC-Telnet' button - runs `/system identity print` and `/system
    resource print` and reports back what it got."""
    out = await run_commands(mac_address, username, password, ["/system identity print", "/system resource print"])
    identity = out.get("/system identity print", "")
    resource = out.get("/system resource print", "")
    name_m = re.search(r"name:\s*(\S+)", identity)
    version_m = re.search(r"version:\s*(\S+)", resource)
    board_m = re.search(r"board-name:\s*(.+)", resource)
    return {
        "ok": True,
        "identity": name_m.group(1) if name_m else None,
        "version": version_m.group(1) if version_m else None,
        "board": board_m.group(1).strip() if board_m else None,
    }
