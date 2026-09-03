"""
Finds CPEs sitting behind a management router.

Three RouterOS data sources are combined, because no single one is reliable
on its own for a mixed fleet of PPPoE clients and bridge-mode antennas:

  - /ip/neighbor  (MNDP/CDP/LLDP "neighbor discovery"): sees RouterOS devices
    at layer 2 even when they have no usable IP address yet - this is often
    the ONLY way to see a fresh bridge-mode antenna.
  - /ip/arp: IP <-> MAC mappings the management router currently knows about.
  - /ip/dhcp-server/lease: anything that has pulled a DHCP lease.
  - /ppp/active + /ppp/secret: PPPoE clients, which have their own routed
    IP/internet access and are frequently NOT visible in ARP/neighbor at all
    if they're one hop further away.

Discovery never overwrites credentials on a CPE that's already been adopted
(given a username/password) - it only fills in newly-seen devices and
refreshes cosmetic fields (identity, model, last-seen IP) on existing ones.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt
from app.models.cpe import CPE, ConnectionMode, DeviceType
from app.models.management_router import ApiType, DeviceStatus, ManagementRouter
from app.models.network import Network
from app.services.device_connect import target_for_management_router
from app.services.routeros_client import ConnectionTarget, RouterOSError, SocksRelay, connect

logger = logging.getLogger(__name__)

DEFAULT_NETWORK_NAME = "Discovered"


@dataclass
class Candidate:
    mac_address: str | None
    host: str | None
    identity: str | None
    model: str | None
    routeros_version: str | None
    source: str
    pppoe_username: str | None = None
    has_internet: bool = False


async def _get_or_create_default_network(db: AsyncSession, router: ManagementRouter, network_id: int | None) -> Network:
    if network_id:
        net = await db.get(Network, network_id)
        if net and net.management_router_id == router.id:
            return net

    result = await db.execute(
        select(Network).where(Network.management_router_id == router.id, Network.name == DEFAULT_NETWORK_NAME)
    )
    net = result.scalar_one_or_none()
    if net:
        return net

    net = Network(management_router_id=router.id, name=DEFAULT_NETWORK_NAME, description="Auto-created by discovery")
    db.add(net)
    await db.flush()
    return net


def _norm_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    return mac.strip().upper().replace("-", ":")


async def scan_candidates(router: ManagementRouter) -> list[Candidate]:
    target = target_for_management_router(router)
    candidates: dict[str, Candidate] = {}  # keyed by mac (preferred) or host

    async with connect(target) as ros:
        # --- neighbor discovery (best source for bridge-mode devices) ---
        try:
            neighbors = await ros.list("ip/neighbor")
        except RouterOSError as e:
            logger.warning("neighbor discovery failed on %s: %s", router.name, e)
            neighbors = []
        for n in neighbors:
            mac = _norm_mac(n.get("mac-address"))
            host = n.get("address") or n.get("address6")
            key = mac or host
            if not key:
                continue
            candidates[key] = Candidate(
                mac_address=mac,
                host=host,
                identity=n.get("identity"),
                model=n.get("board") or n.get("platform"),
                routeros_version=n.get("version"),
                source="neighbor",
            )

        # --- ARP table (fills in / confirms IPs) ---
        try:
            arp_entries = await ros.list("ip/arp")
        except RouterOSError as e:
            logger.warning("arp fetch failed on %s: %s", router.name, e)
            arp_entries = []
        for a in arp_entries:
            mac = _norm_mac(a.get("mac-address"))
            host = a.get("address")
            if not mac and not host:
                continue
            key = mac or host
            existing = candidates.get(key)
            if existing:
                existing.host = existing.host or host
            else:
                candidates[key] = Candidate(mac_address=mac, host=host, identity=None, model=None, routeros_version=None, source="arp")

        # --- DHCP leases ---
        try:
            leases = await ros.list("ip/dhcp-server/lease")
        except RouterOSError as e:
            logger.warning("dhcp lease fetch failed on %s: %s", router.name, e)
            leases = []
        for lease in leases:
            mac = _norm_mac(lease.get("mac-address"))
            host = lease.get("address")
            key = mac or host
            if not key:
                continue
            existing = candidates.get(key)
            hostname = lease.get("host-name")
            if existing:
                existing.host = existing.host or host
                existing.identity = existing.identity or hostname
            else:
                candidates[key] = Candidate(mac_address=mac, host=host, identity=hostname, model=None, routeros_version=None, source="dhcp")

        # --- PPPoE active sessions (these have internet access) ---
        try:
            active = await ros.list("ppp/active")
        except RouterOSError as e:
            logger.warning("ppp active fetch failed on %s: %s", router.name, e)
            active = []
        for sess in active:
            username = sess.get("name")
            caller_id = _norm_mac(sess.get("caller-id"))
            host = sess.get("address")
            key = caller_id or f"pppoe:{username}"
            existing = candidates.get(key) if caller_id else None
            if existing:
                existing.host = existing.host or host
                existing.pppoe_username = username
                existing.has_internet = True
            else:
                candidates[key] = Candidate(
                    mac_address=caller_id,
                    host=host,
                    identity=username,
                    model=None,
                    routeros_version=None,
                    source="pppoe",
                    pppoe_username=username,
                    has_internet=True,
                )

    return list(candidates.values())


async def run_discovery(db: AsyncSession, router: ManagementRouter, network_id: int | None = None) -> dict:
    """Scans the router and upserts CPE rows. Returns a summary dict."""
    candidates = await scan_candidates(router)
    network = await _get_or_create_default_network(db, router, network_id)

    created, updated = 0, 0
    for c in candidates:
        existing = None
        if c.mac_address:
            result = await db.execute(
                select(CPE).where(CPE.management_router_id == router.id, CPE.mac_address == c.mac_address)
            )
            existing = result.scalar_one_or_none()
        if not existing and c.host:
            result = await db.execute(
                select(CPE).where(CPE.management_router_id == router.id, CPE.host == c.host)
            )
            existing = result.scalar_one_or_none()

        if existing:
            existing.host = c.host or existing.host
            existing.model = c.model or existing.model
            existing.routeros_version = c.routeros_version or existing.routeros_version
            if c.has_internet:
                existing.has_internet = True
                existing.pppoe_enabled = True
                existing.pppoe_username = c.pppoe_username or existing.pppoe_username
            if existing.status == DeviceStatus.unknown:
                existing.status = DeviceStatus.online
            existing.last_error = None
            db.add(existing)
            updated += 1
        else:
            cpe = CPE(
                network_id=network.id,
                management_router_id=router.id,
                name=c.identity or c.mac_address or c.host or "unknown-device",
                host=c.host,
                mac_address=c.mac_address,
                device_type=DeviceType.mikrotik_routeros,
                connection_mode=ConnectionMode.unmanaged,
                bridge_mode=not c.has_internet,
                has_internet=c.has_internet,
                pppoe_enabled=c.has_internet,
                pppoe_username=c.pppoe_username,
                role="antenna",
                model=c.model,
                routeros_version=c.routeros_version,
                status=DeviceStatus.online if c.source != "arp" else DeviceStatus.unknown,
            )
            db.add(cpe)
            created += 1

    await db.commit()
    return {"scanned": len(candidates), "created": created, "updated": updated, "network_id": network.id}


def _parse_ip_range(spec: str) -> list[str]:
    """Accepts a CIDR ("10.10.0.0/24"), an inclusive range ("10.10.0.1-10.10.0.50"),
    or a single IP. Refuses anything larger than 65536 addresses as a sanity guard."""
    spec = spec.strip()
    if "/" in spec:
        network = ipaddress.ip_network(spec, strict=False)
        ips = [str(ip) for ip in network.hosts()] or [str(network.network_address)]
    elif "-" in spec:
        start_s, end_s = [p.strip() for p in spec.split("-", 1)]
        start = ipaddress.ip_address(start_s)
        # allow a short form like "10.10.0.1-50"
        end = ipaddress.ip_address(end_s) if "." in end_s else ipaddress.ip_address(
            ".".join(start_s.split(".")[:3] + [end_s])
        )
        if int(end) < int(start):
            raise ValueError("range end must be >= start")
        ips = [str(ipaddress.ip_address(i)) for i in range(int(start), int(end) + 1)]
    else:
        ips = [str(ipaddress.ip_address(spec))]

    if len(ips) > 65536:
        raise ValueError("range too large (max 65536 addresses)")
    return ips


async def scan_ip_range(
    db: AsyncSession,
    router: ManagementRouter,
    ip_range: str,
    *,
    username: str,
    password: str,
    port: int = 443,
    api_type: ApiType = ApiType.rest,
    network_id: int | None = None,
    use_relay: bool = False,
    concurrency: int = 20,
    timeout: float = 4.0,
) -> dict:
    """
    Direct sweep of an IP range: every address that answers to the given
    RouterOS credentials is adopted immediately as a CPE with
    connection_mode=direct (or socks_relay, if use_relay is set) - no
    dependency on the management router's neighbor/ARP/DHCP tables at all.
    This is the right tool when you already know a block of IPs are your
    antennas and they're routable straight from the app (or from the
    management router's SOCKS proxy).
    """
    ips = _parse_ip_range(ip_range)
    network = await _get_or_create_default_network(db, router, network_id)
    semaphore = asyncio.Semaphore(concurrency)

    relay = SocksRelay(host=router.host, port=router.socks_port) if use_relay else None

    async def probe(ip: str) -> tuple[str, dict] | None:
        async with semaphore:
            target = ConnectionTarget(
                host=ip, port=port, username=username, password=password,
                api_type=api_type.value, verify_tls=False, timeout=timeout, relay=relay,
            )
            try:
                async with connect(target) as ros:
                    resource = await ros.get_single("system/resource")
                    identity = await ros.get_single("system/identity")
                return ip, {
                    "version": resource.get("version"),
                    "board": resource.get("board-name"),
                    "identity": identity.get("name") if identity else None,
                }
            except (RouterOSError, OSError, asyncio.TimeoutError):
                return None

    results = await asyncio.gather(*(probe(ip) for ip in ips))
    found = [r for r in results if r is not None]

    created, updated = 0, 0
    for ip, info in found:
        existing = (await db.execute(select(CPE).where(CPE.management_router_id == router.id, CPE.host == ip))).scalar_one_or_none()
        if existing:
            existing.username = username
            existing.password_encrypted = encrypt(password)
            existing.connection_mode = ConnectionMode.socks_relay if use_relay else ConnectionMode.direct
            existing.api_type = api_type
            existing.port = port
            existing.routeros_version = info.get("version") or existing.routeros_version
            existing.model = info.get("board") or existing.model
            existing.status = DeviceStatus.online
            existing.last_error = None
            if info.get("identity"):
                existing.name = info["identity"]
            db.add(existing)
            updated += 1
        else:
            db.add(CPE(
                network_id=network.id,
                management_router_id=router.id,
                name=info.get("identity") or ip,
                host=ip,
                port=port,
                api_type=api_type,
                device_type=DeviceType.mikrotik_routeros,
                connection_mode=ConnectionMode.socks_relay if use_relay else ConnectionMode.direct,
                username=username,
                password_encrypted=encrypt(password),
                role="antenna",
                model=info.get("board"),
                routeros_version=info.get("version"),
                status=DeviceStatus.online,
            ))
            created += 1

    await db.commit()
    return {"addresses_scanned": len(ips), "responded": len(found), "created": created, "updated": updated, "network_id": network.id}
