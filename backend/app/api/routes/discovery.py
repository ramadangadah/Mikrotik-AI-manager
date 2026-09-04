from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.management_router import ApiType, ManagementRouter
from app.models.user import User
from app.services import audit
from app.services.discovery_service import run_discovery, scan_ip_range, scan_management_router_range
from app.services.routeros_client import RouterOSError

router = APIRouter(prefix="/api/discovery", tags=["discovery"], dependencies=[Depends(require_password_set)])


class ManagementRouterRangeScanRequest(BaseModel):
    ip_range: str  # "10.10.0.0/24", "10.10.0.1-10.10.0.50", or a single IP
    username: str
    password: str
    port: int = 443
    api_type: ApiType = ApiType.rest
    verify_tls: bool = False
    use_socks_relay: bool = True
    socks_port: int = 1080
    concurrency: int = 20


# NOTE: registered before the /{router_id}/... routes below on purpose - a
# literal path segment ("management-routers") would otherwise also satisfy
# those routes' {router_id} placeholder, and Starlette matches routes in
# registration order, so this specific one has to come first to win.
@router.post("/management-routers/ip-range-scan")
async def management_router_ip_range_scan(
    payload: ManagementRouterRangeScanRequest,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk-add management routers: tries one shared set of credentials against
    every address in an IP range and registers whatever answers as a brand
    new management router - the same idea as the CPE ip-range-scan below,
    one level up. Addresses that already belong to an existing router are
    left untouched.
    """
    try:
        summary = await scan_management_router_range(
            db, payload.ip_range,
            username=payload.username, password=payload.password, port=payload.port,
            api_type=payload.api_type, verify_tls=payload.verify_tls,
            use_socks_relay=payload.use_socks_relay, socks_port=payload.socks_port,
            concurrency=payload.concurrency,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit.record(db, user.username, "management_router_ip_range_scan", target=payload.ip_range, details=str(summary))
    return summary


class DiscoveryRequest(BaseModel):
    network_id: int | None = None


@router.post("/{router_id}/scan")
async def scan(router_id: int, payload: DiscoveryRequest, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    """
    Indirect discovery: reads the management router's own neighbor/ARP/DHCP/
    PPPoE tables to find CPEs underneath it. Best for bridge-mode antennas
    that have no IP an outside scanner could ever reach directly.
    """
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    try:
        summary = await run_discovery(db, mr, network_id=payload.network_id)
    except RouterOSError as e:
        raise HTTPException(status_code=502, detail=str(e))
    await audit.record(db, user.username, "discovery_scan", target=mr.name, details=str(summary))
    return summary


class IpRangeScanRequest(BaseModel):
    ip_range: str  # "10.10.0.0/24", "10.10.0.1-10.10.0.50", or a single IP
    username: str
    password: str
    port: int = 443
    api_type: ApiType = ApiType.rest
    network_id: int | None = None
    use_relay: bool = False  # False = connect to every IP directly; True = via this router's SOCKS proxy
    concurrency: int = 20


@router.post("/{router_id}/ip-range-scan")
async def ip_range_scan(
    router_id: int,
    payload: IpRangeScanRequest,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Direct discovery: tries the given credentials against every address in
    an IP range and adopts whatever answers as a CPE straight away - no
    dependency on the management router's own tables. Use this when you
    already know a block of IPs are your antennas (e.g. each one is
    individually reachable, one IP per antenna).
    """
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    try:
        summary = await scan_ip_range(
            db, mr, payload.ip_range,
            username=payload.username, password=payload.password, port=payload.port,
            api_type=payload.api_type, network_id=payload.network_id,
            use_relay=payload.use_relay, concurrency=payload.concurrency,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await audit.record(db, user.username, "discovery_ip_range_scan", target=mr.name, details=str(summary))
    return summary
