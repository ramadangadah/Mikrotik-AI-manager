from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin, require_operator, require_password_set
from app.core.crypto import encrypt
from app.core.database import get_db
from app.models.management_router import ManagementRouter
from app.models.router_route import RouterRoute
from app.models.user import User
from app.schemas.router import (
    ManagementRouterCreate,
    ManagementRouterOut,
    ManagementRouterUpdate,
    RouterRouteCreate,
    RouterRouteOut,
)
from app.services import audit, vpn_service
from app.services.device_connect import target_for_management_router
from app.services.routeros_client import RouterOSError, connect

router = APIRouter(prefix="/api/management-routers", tags=["management-routers"], dependencies=[Depends(require_password_set)])


@router.get("", response_model=list[ManagementRouterOut])
async def list_routers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ManagementRouter).order_by(ManagementRouter.name))
    return result.scalars().all()


@router.post("", response_model=ManagementRouterOut, status_code=status.HTTP_201_CREATED)
async def create_router(
    payload: ManagementRouterCreate,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    mr = ManagementRouter(
        name=payload.name,
        host=payload.host,
        port=payload.port,
        api_type=payload.api_type,
        username=payload.username,
        password_encrypted=encrypt(payload.password),
        verify_tls=payload.verify_tls,
        discovery_cidr=payload.discovery_cidr,
        use_socks_relay=payload.use_socks_relay,
        socks_port=payload.socks_port,
        vpn_type=payload.vpn_type,
        vpn_server=payload.vpn_server,
        vpn_username=payload.vpn_username,
        vpn_password_encrypted=encrypt(payload.vpn_password) if payload.vpn_password else None,
        vpn_local_cidr=payload.vpn_local_cidr,
        wg_peer_public_key=payload.wg_peer_public_key,
        wg_preshared_key_encrypted=encrypt(payload.wg_preshared_key) if payload.wg_preshared_key else None,
        wg_endpoint_port=payload.wg_endpoint_port,
        wg_local_address=payload.wg_local_address,
        wg_keepalive=payload.wg_keepalive,
    )
    db.add(mr)
    await audit.record(db, user.username, "management_router_created", target=payload.name, commit=False)
    await db.commit()
    await db.refresh(mr)
    return mr


@router.get("/{router_id}", response_model=ManagementRouterOut)
async def get_router(router_id: int, db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    return mr


@router.patch("/{router_id}", response_model=ManagementRouterOut)
async def update_router(
    router_id: int,
    payload: ManagementRouterUpdate,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")

    data = payload.model_dump(exclude_unset=True)
    if "password" in data:
        mr.password_encrypted = encrypt(data.pop("password"))
    if "vpn_password" in data:
        vpn_pw = data.pop("vpn_password")
        if vpn_pw:
            mr.vpn_password_encrypted = encrypt(vpn_pw)
    if "wg_preshared_key" in data:
        psk = data.pop("wg_preshared_key")
        if psk:
            mr.wg_preshared_key_encrypted = encrypt(psk)
    for k, v in data.items():
        setattr(mr, k, v)

    db.add(mr)
    await audit.record(db, user.username, "management_router_updated", target=mr.name, commit=False)
    await db.commit()
    await db.refresh(mr)
    return mr


@router.delete("/{router_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_router(router_id: int, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    await db.delete(mr)
    await audit.record(db, user.username, "management_router_deleted", target=mr.name, commit=False)
    await db.commit()


@router.post("/{router_id}/test-connection")
async def test_connection(router_id: int, db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    target = target_for_management_router(mr)
    try:
        async with connect(target) as ros:
            identity = await ros.get_single("system/identity")
            resource = await ros.get_single("system/resource")
        return {
            "ok": True,
            "identity": identity.get("name"),
            "version": resource.get("version"),
            "board": resource.get("board-name"),
        }
    except RouterOSError as e:
        raise HTTPException(status_code=502, detail=str(e))


# --- VPN tunnel management (PPTP / L2TP / WireGuard into the router's own LAN) ---

@router.post("/{router_id}/vpn/generate-wireguard-keys", response_model=ManagementRouterOut)
async def generate_wireguard_keys(router_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    """Generates this app's WireGuard keypair for the tunnel and returns the
    public key (in wg_public_key) to paste into the router's WireGuard peer config."""
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    mr = await vpn_service.generate_wireguard_keys(db, mr)
    await audit.record(db, user.username, "vpn_wireguard_keys_generated", target=mr.name)
    return mr


@router.post("/{router_id}/vpn/connect", response_model=ManagementRouterOut)
async def vpn_connect(router_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    if mr.vpn_type.value == "none":
        raise HTTPException(status_code=400, detail="Set a vpn_type (pptp, l2tp, or wireguard) on this router first")
    try:
        mr = await vpn_service.connect(db, mr)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    await audit.record(db, user.username, "vpn_connect", target=mr.name, details=f"status={mr.vpn_status.value}")
    if mr.vpn_status.value == "error":
        raise HTTPException(status_code=502, detail=mr.vpn_last_error or "VPN connection failed")
    return mr


@router.post("/{router_id}/vpn/disconnect", response_model=ManagementRouterOut)
async def vpn_disconnect(router_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    mr = await vpn_service.disconnect(db, mr)
    await audit.record(db, user.username, "vpn_disconnect", target=mr.name)
    return mr


@router.get("/{router_id}/vpn/status", response_model=ManagementRouterOut)
async def vpn_status(router_id: int, db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    return await vpn_service.refresh_status(db, mr)


# --- Private network routes (which CIDRs are reachable through this router's tunnel) ---

@router.get("/{router_id}/routes", response_model=list[RouterRouteOut])
async def list_routes(router_id: int, db: AsyncSession = Depends(get_db)):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    result = await db.execute(
        select(RouterRoute).where(RouterRoute.management_router_id == router_id).order_by(RouterRoute.created_at)
    )
    return result.scalars().all()


@router.post("/{router_id}/routes", response_model=RouterRouteOut, status_code=status.HTTP_201_CREATED)
async def add_route(
    router_id: int,
    payload: RouterRouteCreate,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    route = RouterRoute(management_router_id=router_id, cidr=payload.cidr, description=payload.description)
    db.add(route)
    await audit.record(db, user.username, "router_route_added", target=mr.name, details=payload.cidr, commit=False)
    await db.commit()
    await db.refresh(route)
    # A route added/changed while the tunnel is already up should take effect
    # without requiring a manual disconnect/reconnect.
    if mr.vpn_status.value == "connected":
        try:
            await vpn_service.apply_routes(db, mr)
        except Exception:
            pass
    return route


@router.delete("/{router_id}/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(
    router_id: int,
    route_id: int,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    mr = await db.get(ManagementRouter, router_id)
    if not mr:
        raise HTTPException(status_code=404, detail="Management router not found")
    route = await db.get(RouterRoute, route_id)
    if not route or route.management_router_id != router_id:
        raise HTTPException(status_code=404, detail="Route not found")
    cidr = route.cidr
    await db.delete(route)
    await audit.record(db, user.username, "router_route_removed", target=mr.name, details=cidr, commit=False)
    await db.commit()
    if mr.vpn_status.value == "connected":
        try:
            await vpn_service.apply_routes(db, mr)
        except Exception:
            pass
