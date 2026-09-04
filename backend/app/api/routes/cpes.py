from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.crypto import decrypt, encrypt
from app.core.database import get_db
from app.models.cpe import CPE
from app.models.management_router import ManagementRouter
from app.models.metric import MetricSample
from app.models.network import Network
from app.models.user import User
from app.schemas.cpe import BulkAdoptRequest, BulkMactelnetSyncRequest, CPECreate, CPEOut, CPEUpdate
from app.services import audit, mactelnet_service
from app.services.device_connect import target_for_cpe
from app.services.routeros_client import RouterOSError, connect

router = APIRouter(prefix="/api/cpes", tags=["cpes"], dependencies=[Depends(require_password_set)])


@router.get("", response_model=list[CPEOut])
async def list_cpes(
    network_id: int | None = None,
    management_router_id: int | None = None,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(CPE)
    if network_id:
        query = query.where(CPE.network_id == network_id)
    if management_router_id:
        query = query.where(CPE.management_router_id == management_router_id)
    if status_filter:
        query = query.where(CPE.status == status_filter)
    result = await db.execute(query.order_by(CPE.name))
    return result.scalars().all()


@router.post("", response_model=CPEOut, status_code=status.HTTP_201_CREATED)
async def create_cpe(payload: CPECreate, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    net = await db.get(Network, payload.network_id)
    if not net:
        raise HTTPException(status_code=404, detail="Network not found")

    data = payload.model_dump()
    password = data.pop("password", None)
    cpe = CPE(**data, management_router_id=net.management_router_id, password_encrypted=encrypt(password) if password else None)
    db.add(cpe)
    await audit.record(db, user.username, "cpe_created", target=payload.name, commit=False)
    await db.commit()
    await db.refresh(cpe)
    return cpe


@router.get("/{cpe_id}", response_model=CPEOut)
async def get_cpe(cpe_id: int, db: AsyncSession = Depends(get_db)):
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    return cpe


@router.patch("/{cpe_id}", response_model=CPEOut)
async def update_cpe(cpe_id: int, payload: CPEUpdate, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        pw = data.pop("password")
        cpe.password_encrypted = encrypt(pw) if pw else None
    for k, v in data.items():
        setattr(cpe, k, v)
    db.add(cpe)
    await audit.record(db, user.username, "cpe_updated", target=cpe.name, commit=False)
    await db.commit()
    await db.refresh(cpe)
    return cpe


@router.delete("/{cpe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cpe(cpe_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    await db.delete(cpe)
    await audit.record(db, user.username, "cpe_deleted", target=cpe.name, commit=False)
    await db.commit()


@router.post("/bulk-adopt", response_model=list[CPEOut])
async def bulk_adopt(payload: BulkAdoptRequest, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    """
    Apply one shared username/password/connection-mode to many freshly
    discovered CPEs at once - the common case where every antenna in the
    field was provisioned with the same admin credentials.
    """
    result = await db.execute(select(CPE).where(CPE.id.in_(payload.cpe_ids)))
    cpes = result.scalars().all()
    for cpe in cpes:
        cpe.username = payload.username
        cpe.password_encrypted = encrypt(payload.password)
        cpe.connection_mode = payload.connection_mode
        cpe.api_type = payload.api_type
        db.add(cpe)
    await audit.record(db, user.username, "cpe_bulk_adopt", target=f"{len(cpes)} CPEs", commit=False)
    await db.commit()
    for cpe in cpes:
        await db.refresh(cpe)
    return cpes


@router.post("/bulk-mactelnet-sync")
async def bulk_mactelnet_sync(payload: BulkMactelnetSyncRequest, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    """
    "Synchronize a range of CPEs one by one via MAC-Telnet using one shared
    username/password" - applies the same credentials to every listed CPE,
    testing each one in turn over MAC-Telnet (see mactelnet_service.bulk_sync
    for why this is sequential rather than parallel like the IP-range scan),
    and adopts (saves the credentials on) whichever ones respond. CPEs with
    no MAC address on file are skipped - run a router-table discovery scan
    first (POST /api/discovery/{router_id}/scan) to capture those.
    """
    result = await db.execute(select(CPE).where(CPE.id.in_(payload.cpe_ids)))
    cpes = result.scalars().all()
    summary = await mactelnet_service.bulk_sync(db, cpes, payload.username, payload.password)
    await audit.record(
        db, user.username, "cpe_bulk_mactelnet_sync",
        target=f"{len(cpes)} CPEs", details=f"synced={summary['synced']} failed={summary['failed']} skipped={summary['skipped']}",
    )
    return summary


@router.post("/{cpe_id}/test-connection")
async def test_cpe_connection(cpe_id: int, db: AsyncSession = Depends(get_db)):
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    router_row = await db.get(ManagementRouter, cpe.management_router_id)
    target = target_for_cpe(cpe, router_row)
    try:
        async with connect(target) as ros:
            resource = await ros.get_single("system/resource")
        return {"ok": True, "version": resource.get("version"), "board": resource.get("board-name")}
    except RouterOSError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/{cpe_id}/test-mactelnet")
async def test_cpe_mactelnet(cpe_id: int, db: AsyncSession = Depends(get_db)):
    """
    Same idea as /test-connection, but reaches the CPE by its captured MAC
    address over MikroTik's MAC-Telnet protocol instead of its IP - useful
    to confirm a freshly-discovered bridge-mode device (no IP yet, or one
    you don't want to route through) is actually reachable and the stored
    credentials work, before relying on it. Only works when this app has
    layer-2 reachability to the CPE's segment - see mactelnet_service.py.
    """
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    if not cpe.mac_address:
        raise HTTPException(status_code=400, detail="This CPE has no MAC address on file yet (run discovery via the router's tables first)")
    if not cpe.username:
        raise HTTPException(status_code=400, detail="Set a username/password on this CPE first")
    try:
        result = await mactelnet_service.test_reachable(
            cpe.mac_address, cpe.username, decrypt(cpe.password_encrypted) if cpe.password_encrypted else ""
        )
        return result
    except mactelnet_service.MacTelnetError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/{cpe_id}/metrics")
async def cpe_metrics(cpe_id: int, metric_type: str, hours: int = 24, db: AsyncSession = Depends(get_db)):
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    result = await db.execute(
        select(MetricSample.timestamp, MetricSample.value).where(
            MetricSample.cpe_id == cpe_id,
            MetricSample.metric_type == metric_type,
            MetricSample.timestamp >= since,
        ).order_by(MetricSample.timestamp)
    )
    return [{"timestamp": r.timestamp.isoformat(), "value": r.value} for r in result.all()]
