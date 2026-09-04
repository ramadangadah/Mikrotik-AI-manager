"""
Dials a PPTP or L2TP VPN straight into a management router's own LAN - the
same way a technician would connect from a laptop to reach a site remotely -
so every CPE on that LAN becomes reachable at the OS routing level. This is
an alternative to the SOCKS relay (services/routeros_client.py's SocksRelay):
SOCKS relays one app-level TCP connection at a time through the router;
a VPN tunnel instead makes the whole remote subnet routable, which some
sites' MikroTik routers are already set up to offer (they're commonly used
as PPTP/L2TP *servers* for exactly this kind of remote-management access).

Requires the container to be started with NET_ADMIN capability and access
to /dev/ppp (see docker-compose.yml) - this can't be granted after the
container is already running, so it has to be present from the start even
if you don't use the VPN feature on every deployment.

How it works:
  1. We write a CHAP secret (pppd only supports plaintext-on-disk secrets -
     that's a limitation of the ppp daemon itself, not this app; the file is
     root-only, 0600, and entries are removed again on disconnect) and spawn
     `pppd` (directly for PPTP via the `pty "pptp ..."` trick, or via xl2tpd
     for L2TP).
  2. pppd calls our ip-up.d/ip-down.d hook scripts (installed by the Docker
     image) when the link comes up/down. The hook reads the target LAN CIDR
     we stashed in /run/vpn-tunnels/<tag>.cidr, adds/removes a route through
     the new ppp interface, and drops a marker file we poll for.
  3. Once connected, CPEs adopted with connection_mode="vpn_tunnel" (which
     behaves identically to "direct" at the connector level - see
     device_connect.py) are simply reachable, no relay needed per-request.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt, encrypt
from app.models.management_router import ManagementRouter, VpnStatus, VpnType
from app.models.router_route import RouterRoute

logger = logging.getLogger(__name__)

CHAP_SECRETS_PATH = "/etc/ppp/chap-secrets"
RUN_DIR = "/run/vpn-tunnels"
XL2TPD_CONF = "/etc/xl2tpd/xl2tpd.conf"
WIREGUARD_DIR = "/etc/wireguard"
CONNECT_TIMEOUT_S = 25

_file_lock = asyncio.Lock()
_pptp_processes: dict[int, asyncio.subprocess.Process] = {}
_xl2tpd_process: asyncio.subprocess.Process | None = None


def _tag(router: ManagementRouter) -> str:
    return f"router{router.id}"


async def _route_cidrs(db: AsyncSession, router: ManagementRouter) -> list[str]:
    """
    The private-network ranges this router's tunnel should carry, from the
    "Private network routes" table (management-routers/{id}/routes). Falls
    back to the legacy single vpn_local_cidr field for routers set up before
    that table existed, so nothing already deployed silently stops routing.
    """
    result = await db.execute(
        select(RouterRoute.cidr).where(RouterRoute.management_router_id == router.id).order_by(RouterRoute.created_at)
    )
    cidrs = [r for r in result.scalars().all() if r]
    if cidrs:
        return cidrs
    return [router.vpn_local_cidr] if router.vpn_local_cidr else []


def _remotename(router: ManagementRouter) -> str:
    return f"app-{_tag(router)}"


async def _write_chap_secret(remotename: str, username: str, password: str) -> None:
    async with _file_lock:
        lines = []
        if os.path.exists(CHAP_SECRETS_PATH):
            with open(CHAP_SECRETS_PATH) as f:
                lines = [ln for ln in f.read().splitlines() if f' {remotename} ' not in ln]
        lines.append(f'"{username}" {remotename} "{password}" *')
        os.makedirs(os.path.dirname(CHAP_SECRETS_PATH), exist_ok=True)
        with open(CHAP_SECRETS_PATH, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(CHAP_SECRETS_PATH, 0o600)


async def _remove_chap_secret(remotename: str) -> None:
    async with _file_lock:
        if not os.path.exists(CHAP_SECRETS_PATH):
            return
        with open(CHAP_SECRETS_PATH) as f:
            lines = [ln for ln in f.read().splitlines() if f' {remotename} ' not in ln]
        with open(CHAP_SECRETS_PATH, "w") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))


def _write_cidr_file(tag: str, cidrs: list[str]) -> None:
    """One CIDR per line - read by ppp-ip-up.sh/ppp-ip-down.sh, which loop
    over every non-blank line to add/remove a route per private network."""
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(os.path.join(RUN_DIR, f"{tag}.cidr"), "w") as f:
        f.write("\n".join(c for c in cidrs if c) + ("\n" if cidrs else ""))


def _up_marker_path(tag: str) -> str:
    return os.path.join(RUN_DIR, f"{tag}.up")


async def _wait_for_up(tag: str, timeout: float = CONNECT_TIMEOUT_S) -> str | None:
    marker = _up_marker_path(tag)
    elapsed = 0.0
    step = 0.5
    while elapsed < timeout:
        if os.path.exists(marker):
            with open(marker) as f:
                iface = f.read().strip()
            if iface:
                return iface
        await asyncio.sleep(step)
        elapsed += step
    return None


async def _kill_stale(pattern: str) -> None:
    """Best-effort cleanup of a previous tunnel attempt for the same router,
    including across app restarts (when we no longer hold the Process handle)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "pkill", "-f", pattern, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
    except FileNotFoundError:
        pass  # pkill not installed - non-fatal, just means we rely on ports being reused


async def connect(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    if router.vpn_type == VpnType.pptp:
        return await _connect_pptp(db, router)
    if router.vpn_type == VpnType.l2tp:
        return await _connect_l2tp(db, router)
    if router.vpn_type == VpnType.wireguard:
        return await _connect_wireguard(db, router)
    raise ValueError("vpn_type is not set to pptp, l2tp, or wireguard on this management router")


async def _connect_pptp(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    tag = _tag(router)
    remotename = _remotename(router)
    server = router.vpn_server or router.host
    password = decrypt(router.vpn_password_encrypted) if router.vpn_password_encrypted else ""

    router.vpn_status = VpnStatus.connecting
    router.vpn_last_error = None
    db.add(router)
    await db.commit()

    await _kill_stale(f"ipparam {tag}")
    try:
        if os.path.exists(_up_marker_path(tag)):
            os.remove(_up_marker_path(tag))
    except OSError:
        pass

    await _write_chap_secret(remotename, router.vpn_username or "", password)
    _write_cidr_file(tag, await _route_cidrs(db, router))

    args = [
        "pty", f"pptp {server} --nolaunchpppd",
        "name", router.vpn_username or "",
        "remotename", remotename,
        "ipparam", tag,
        "require-mschap-v2", "refuse-eap", "refuse-pap",
        "novj", "novjccomp", "nobsdcomp",
        "noauth", "nodefaultroute", "lock", "nodetach",
        "mtu", "1400", "mru", "1400",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            "pppd", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = "pppd/pptp not installed in this container image"
        db.add(router)
        await db.commit()
        return router

    _pptp_processes[router.id] = proc
    return await _finish_connect(db, router, tag, proc)


async def _connect_l2tp(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    tag = _tag(router)
    remotename = _remotename(router)
    server = router.vpn_server or router.host
    password = decrypt(router.vpn_password_encrypted) if router.vpn_password_encrypted else ""

    router.vpn_status = VpnStatus.connecting
    router.vpn_last_error = None
    db.add(router)
    await db.commit()

    await _write_chap_secret(remotename, router.vpn_username or "", password)
    _write_cidr_file(tag, await _route_cidrs(db, router))

    options_path = f"/etc/ppp/options.l2tpd.{tag}"
    os.makedirs(os.path.dirname(options_path), exist_ok=True)
    with open(options_path, "w") as f:
        f.write(
            "\n".join([
                f"ipparam {tag}",
                f"name {router.vpn_username or ''}",
                f"remotename {remotename}",
                "require-chap", "refuse-pap", "refuse-eap",
                "novj", "novjccomp", "nodefaultroute", "noauth", "lock",
                "mtu 1400", "mru 1400", "",
            ])
        )

    await _regenerate_xl2tpd_conf(db)
    await _restart_xl2tpd()
    await asyncio.sleep(1.5)  # let the daemon finish binding before we ask it to dial

    try:
        proc = await asyncio.create_subprocess_exec(
            "xl2tpd-control", "connect", tag,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        await proc.wait()
    except FileNotFoundError:
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = "xl2tpd not installed in this container image"
        db.add(router)
        await db.commit()
        return router

    return await _finish_connect(db, router, tag, None)


def _wg_iface(router: ManagementRouter) -> str:
    return f"wgr{router.id}"  # Linux interface names are capped at 15 chars - safe for realistic router IDs


async def generate_wireguard_keys(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    """
    Generates a fresh keypair for this app's side of the tunnel and stores
    it (private key encrypted, public key in the clear since it isn't
    secret). Returns the router so the caller can hand the public key back
    to the admin to paste into the router's WireGuard peer configuration -
    do this BEFORE calling connect(), since WireGuard needs both sides
    configured with each other's public key up front.
    """
    priv_proc = await asyncio.create_subprocess_exec("wg", "genkey", stdout=asyncio.subprocess.PIPE)
    priv_out, _ = await priv_proc.communicate()
    private_key = priv_out.decode().strip()

    pub_proc = await asyncio.create_subprocess_exec(
        "wg", "pubkey", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE
    )
    pub_out, _ = await pub_proc.communicate(input=private_key.encode())
    public_key = pub_out.decode().strip()

    router.wg_private_key_encrypted = encrypt(private_key)
    router.wg_public_key = public_key
    db.add(router)
    await db.commit()
    await db.refresh(router)
    return router


async def _connect_wireguard(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    if not router.wg_private_key_encrypted:
        await generate_wireguard_keys(db, router)
        await db.refresh(router)

    if not router.wg_peer_public_key or not router.wg_local_address:
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = (
            "WireGuard needs wg_peer_public_key (the router's own WireGuard public key) and "
            "wg_local_address (the tunnel IP to assign this app, e.g. 10.10.0.250/32) set first."
        )
        db.add(router)
        await db.commit()
        await db.refresh(router)
        return router

    router.vpn_status = VpnStatus.connecting
    db.add(router)
    await db.commit()

    iface = _wg_iface(router)
    server = router.vpn_server or router.host
    private_key = decrypt(router.wg_private_key_encrypted)
    preshared = decrypt(router.wg_preshared_key_encrypted) if router.wg_preshared_key_encrypted else None
    cidrs = await _route_cidrs(db, router)
    allowed_ips = ", ".join(cidrs) if cidrs else (router.wg_local_address or "0.0.0.0/0")

    os.makedirs(WIREGUARD_DIR, exist_ok=True)
    lines = [
        "[Interface]",
        f"PrivateKey = {private_key}",
        f"Address = {router.wg_local_address}",
        "",
        "[Peer]",
        f"PublicKey = {router.wg_peer_public_key}",
        f"Endpoint = {server}:{router.wg_endpoint_port}",
        f"AllowedIPs = {allowed_ips}",
        f"PersistentKeepalive = {router.wg_keepalive}",
    ]
    if preshared:
        lines.append(f"PresharedKey = {preshared}")

    conf_path = os.path.join(WIREGUARD_DIR, f"{iface}.conf")
    async with _file_lock:
        with open(conf_path, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.chmod(conf_path, 0o600)

    # Idempotent: tear down any previous instance of this interface first
    # (e.g. reconnecting after an edited config) - errors here are expected
    # and harmless if it wasn't up.
    down = await asyncio.create_subprocess_exec(
        "wg-quick", "down", iface, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await down.wait()

    try:
        up = await asyncio.create_subprocess_exec(
            "wg-quick", "up", iface, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await up.communicate()
    except FileNotFoundError:
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = "wireguard-tools (wg-quick) not installed in this container image"
        db.add(router)
        await db.commit()
        await db.refresh(router)
        return router

    if up.returncode == 0 and os.path.isdir(f"/sys/class/net/{iface}"):
        router.vpn_status = VpnStatus.connected
        router.vpn_interface = iface
        router.vpn_connected_at = datetime.now(timezone.utc)
        router.vpn_last_error = None
    else:
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = out.decode(errors="replace")[-500:] if out else "wg-quick up failed"

    db.add(router)
    await db.commit()
    await db.refresh(router)
    return router


async def _disconnect_wireguard(router: ManagementRouter) -> None:
    iface = _wg_iface(router)
    try:
        proc = await asyncio.create_subprocess_exec(
            "wg-quick", "down", iface, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        await proc.wait()
    except FileNotFoundError:
        pass


async def _finish_connect(db: AsyncSession, router: ManagementRouter, tag: str, proc) -> ManagementRouter:
    iface = await _wait_for_up(tag)
    if iface:
        router.vpn_status = VpnStatus.connected
        router.vpn_interface = iface
        router.vpn_connected_at = datetime.now(timezone.utc)
        router.vpn_last_error = None
    else:
        tail = ""
        if proc is not None:
            try:
                proc.kill()
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
                tail = out.decode(errors="replace")[-400:] if out else ""
            except Exception:
                pass
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = f"tunnel did not come up within {CONNECT_TIMEOUT_S}s. {tail}".strip()[:500]

    db.add(router)
    await db.commit()
    await db.refresh(router)
    return router


async def disconnect(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    tag = _tag(router)
    remotename = _remotename(router)

    if router.vpn_type == VpnType.pptp:
        proc = _pptp_processes.pop(router.id, None)
        if proc and proc.returncode is None:
            proc.send_signal(signal.SIGTERM)
        await _kill_stale(f"ipparam {tag}")
        await _remove_chap_secret(remotename)
        try:
            marker = _up_marker_path(tag)
            if os.path.exists(marker):
                os.remove(marker)
        except OSError:
            pass
    elif router.vpn_type == VpnType.l2tp:
        try:
            proc = await asyncio.create_subprocess_exec("xl2tpd-control", "disconnect", tag)
            await proc.wait()
        except FileNotFoundError:
            pass
        await _remove_chap_secret(remotename)
        try:
            marker = _up_marker_path(tag)
            if os.path.exists(marker):
                os.remove(marker)
        except OSError:
            pass
    elif router.vpn_type == VpnType.wireguard:
        await _disconnect_wireguard(router)

    router.vpn_status = VpnStatus.disconnected
    router.vpn_interface = None
    router.vpn_connected_at = None
    db.add(router)
    await db.commit()
    await db.refresh(router)
    return router


async def apply_routes(db: AsyncSession, router: ManagementRouter) -> None:
    """
    Pushes the current "Private network routes" list onto an *already
    connected* tunnel, without a disconnect/reconnect - called whenever a
    route is added or removed on a router whose tunnel is currently up (see
    api/routes/management_routers.py), so editing the routing table takes
    effect immediately instead of only on the next reconnect.
    """
    cidrs = await _route_cidrs(db, router)

    if router.vpn_type == VpnType.wireguard:
        if not router.vpn_interface or not router.wg_peer_public_key:
            return
        allowed_ips = ", ".join(cidrs) if cidrs else (router.wg_local_address or "0.0.0.0/0")
        try:
            proc = await asyncio.create_subprocess_exec(
                "wg", "set", router.vpn_interface, "peer", router.wg_peer_public_key,
                "allowed-ips", allowed_ips,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except FileNotFoundError:
            logger.warning("wg binary not found - could not live-update AllowedIPs for router %s", router.id)
        return

    # PPTP/L2TP: diff the previously-applied CIDRs (stashed in the .cidr
    # file ppp-ip-up.sh wrote them into) against the current list, and add/
    # remove routes directly on the already-up ppp interface - the ip-up/
    # ip-down hooks only run when the link itself comes up or down, not on
    # a routing-table edit while it's already connected.
    if not router.vpn_interface:
        return
    tag = _tag(router)
    cidr_path = os.path.join(RUN_DIR, f"{tag}.cidr")
    old_cidrs: set[str] = set()
    if os.path.exists(cidr_path):
        with open(cidr_path) as f:
            old_cidrs = {ln.strip() for ln in f if ln.strip()}
    new_cidrs = {c for c in cidrs if c}

    for cidr in old_cidrs - new_cidrs:
        proc = await asyncio.create_subprocess_exec(
            "ip", "route", "del", cidr, "dev", router.vpn_interface,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    for cidr in new_cidrs - old_cidrs:
        proc = await asyncio.create_subprocess_exec(
            "ip", "route", "replace", cidr, "dev", router.vpn_interface,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    _write_cidr_file(tag, list(new_cidrs))


async def refresh_status(db: AsyncSession, router: ManagementRouter) -> ManagementRouter:
    """Verifies a 'connected' tunnel is still actually up: for PPTP/L2TP the
    marker file disappears the moment pppd's ip-down hook runs (e.g. after a
    drop); for WireGuard we check the interface still exists."""
    if router.vpn_status != VpnStatus.connected:
        return router

    still_up = True
    if router.vpn_type == VpnType.wireguard:
        still_up = os.path.isdir(f"/sys/class/net/{_wg_iface(router)}")
    else:
        still_up = os.path.exists(_up_marker_path(_tag(router)))

    if not still_up:
        router.vpn_status = VpnStatus.error
        router.vpn_last_error = "tunnel dropped unexpectedly"
        router.vpn_interface = None
        db.add(router)
        await db.commit()
        await db.refresh(router)
    return router


async def _regenerate_xl2tpd_conf(db: AsyncSession) -> None:
    from sqlalchemy import select

    routers = (
        await db.execute(select(ManagementRouter).where(ManagementRouter.vpn_type == VpnType.l2tp))
    ).scalars().all()

    os.makedirs(os.path.dirname(XL2TPD_CONF), exist_ok=True)
    parts = ["[global]", "port = 1701", ""]
    for r in routers:
        tag = _tag(r)
        server = r.vpn_server or r.host
        parts += [
            f"[lac {tag}]",
            f"lns = {server}",
            "ppp debug = yes",
            f"pppoptfile = /etc/ppp/options.l2tpd.{tag}",
            "length bit = yes",
            "",
        ]
    with open(XL2TPD_CONF, "w") as f:
        f.write("\n".join(parts))


async def _restart_xl2tpd() -> None:
    global _xl2tpd_process
    await _kill_stale("xl2tpd -D")
    try:
        _xl2tpd_process = await asyncio.create_subprocess_exec(
            "xl2tpd", "-c", XL2TPD_CONF, "-D",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.warning("xl2tpd binary not found - L2TP tunnels unavailable in this image")
