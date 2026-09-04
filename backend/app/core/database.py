from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

os.makedirs(settings.DATA_DIR, exist_ok=True)

connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    # Import models so they're registered on Base.metadata before create_all.
    from app.models import (  # noqa: F401
        alert,
        app_setting,
        audit_log,
        config_backup,
        connectivity_test,
        cpe,
        firmware,
        job,
        management_router,
        metric,
        network,
        pppoe_secret,
        router_route,
        user,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(sync_conn) -> None:
    """
    There's no Alembic/migration framework here - schema changes normally
    just mean a brand new table, which create_all() above handles fine on
    its own. But a NEW COLUMN on an EXISTING table (like this session's
    wg_peer_address on management_routers) would otherwise silently never
    appear on a database that already existed before the column was added -
    every query touching that column would start failing with "no such
    column" on an already-deployed app until someone deleted the whole
    database (losing everything) or hand-ran an ALTER TABLE.

    This runs on every startup, inspects what columns each table actually
    has versus what the ORM models declare, and ALTER TABLE ... ADD COLUMN
    for whatever's missing - always as a nullable column regardless of what
    the model says, since a NOT NULL column can't be added to a table that
    already has rows without a backfill value. Existing rows just get NULL
    for the new column until the app writes a real value; new rows still go
    through the model's normal Python-side defaults. Best-effort: a single
    column that fails to add is logged and skipped rather than aborting
    startup.
    """
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all() just made this one fresh - every column is already present
        existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_cols:
                continue
            try:
                col_type = column.type.compile(dialect=sync_conn.dialect)
                sync_conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))
                logger.info("migrated: added column %s.%s", table.name, column.name)
            except Exception as e:  # noqa: BLE001 - best-effort, never block startup over one column
                logger.warning("could not add column %s.%s (%s) - continuing", table.name, column.name, e)
