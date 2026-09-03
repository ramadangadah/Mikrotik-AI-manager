from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.cpe import CPE
from app.models.network import Network
from app.models.user import User
from app.schemas.network import NetworkCreate, NetworkOut, NetworkUpdate
from app.services import audit

router = APIRouter(prefix="/api/networks", tags=["networks"], dependencies=[Depends(require_password_set)])


@router.get("", response_model=list[NetworkOut])
async def list_networks(management_router_id: int | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Network, func.count(CPE.id)).outerjoin(CPE, CPE.network_id == Network.id)
    if management_router_id:
        query = query.where(Network.management_router_id == management_router_id)
    query = query.group_by(Network.id).order_by(Network.name)
    rows = (await db.execute(query)).all()
    out = []
    for net, count in rows:
        item = NetworkOut.model_validate(net)
        item.cpe_count = count
        out.append(item)
    return out


@router.post("", response_model=NetworkOut, status_code=status.HTTP_201_CREATED)
async def create_network(payload: NetworkCreate, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    net = Network(**payload.model_dump())
    db.add(net)
    await audit.record(db, user.username, "network_created", target=payload.name, commit=False)
    await db.commit()
    await db.refresh(net)
    return net


@router.patch("/{network_id}", response_model=NetworkOut)
async def update_network(network_id: int, payload: NetworkUpdate, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    net = await db.get(Network, network_id)
    if not net:
        raise HTTPException(status_code=404, detail="Network not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(net, k, v)
    db.add(net)
    await audit.record(db, user.username, "network_updated", target=net.name, commit=False)
    await db.commit()
    await db.refresh(net)
    return net


@router.delete("/{network_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_network(network_id: int, user: User = Depends(require_operator), db: AsyncSession = Depends(get_db)):
    net = await db.get(Network, network_id)
    if not net:
        raise HTTPException(status_code=404, detail="Network not found")
    await db.delete(net)
    await audit.record(db, user.username, "network_deleted", target=net.name, commit=False)
    await db.commit()
