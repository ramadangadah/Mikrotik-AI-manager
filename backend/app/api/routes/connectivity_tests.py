from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_operator, require_password_set
from app.core.database import get_db
from app.models.connectivity_test import ConnectivityTest
from app.models.cpe import CPE
from app.models.user import User
from app.schemas.connectivity_test import ConnectivityTestManualUpdate, ConnectivityTestOut, ConnectivityTestRun
from app.services import audit, connectivity_test_service
from app.services.runtime_settings import get_effective

router = APIRouter(prefix="/api", tags=["connectivity-tests"], dependencies=[Depends(require_password_set)])


@router.post("/cpes/{cpe_id}/connectivity-tests", response_model=ConnectivityTestOut, status_code=status.HTTP_201_CREATED)
async def run_connectivity_test(
    cpe_id: int,
    payload: ConnectivityTestRun,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """
    Runs the client connectivity test checklist against this CPE right now
    (radio checks + network tests, over IP or MAC-Telnet - see
    connectivity_test_service.py) and saves the result. Whatever couldn't
    be automated is left null for a technician to fill in afterwards via
    PATCH /api/connectivity-tests/{id}.
    """
    cpe = await db.get(CPE, cpe_id)
    if not cpe:
        raise HTTPException(status_code=404, detail="CPE not found")
    eff = await get_effective(db)
    test = await connectivity_test_service.run_test(db, cpe, payload.method, user.username, eff)
    await audit.record(
        db, user.username, "connectivity_test_run", target=cpe.name,
        details=f"method={payload.method.value}" + (f", error={test.run_error}" if test.run_error else ""),
    )
    return test


@router.get("/cpes/{cpe_id}/connectivity-tests", response_model=list[ConnectivityTestOut])
async def list_connectivity_tests(cpe_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ConnectivityTest).where(ConnectivityTest.cpe_id == cpe_id).order_by(ConnectivityTest.created_at.desc())
    )
    return result.scalars().all()


@router.get("/connectivity-tests/{test_id}", response_model=ConnectivityTestOut)
async def get_connectivity_test(test_id: int, db: AsyncSession = Depends(get_db)):
    test = await db.get(ConnectivityTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Connectivity test not found")
    return test


@router.patch("/connectivity-tests/{test_id}", response_model=ConnectivityTestOut)
async def update_connectivity_test(
    test_id: int,
    payload: ConnectivityTestManualUpdate,
    user: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
):
    """Fills in the parts of the checklist that can't be automated: whether
    the router/PoE was power-cycled, the TP-Link router's own speed-test
    result, and the client PC's fast.com result - each pasted in by the
    technician who ran the test."""
    test = await db.get(ConnectivityTest, test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Connectivity test not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(test, k, v)
    db.add(test)
    await audit.record(db, user.username, "connectivity_test_updated", target=f"test #{test.id}", commit=False)
    await db.commit()
    await db.refresh(test)
    return test
