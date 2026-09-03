from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.management_router import ApiType, ManagementRouter
from app.models.user import User
from app.services import audit
from app.services.discovery_service import run_discovery, scan_ip_range
from app.services.routeros_client import RouterOSError

router = APIRouter(prefix="/api/discovery", tags=["discovery"], dependencies=[Depends(require_password_set)])


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
