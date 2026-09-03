from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)
settings = get_settings()


async def seed_default_admin() -> None:
    """
    On a completely fresh install (no users in the DB yet), create the
    default admin account from ADMIN_USERNAME/ADMIN_PASSWORD (default
    admin/admin) with must_change_password=True, so the very first login
    is forced through the "choose a new password" screen before anything
    else in the app becomes usable.
    """
    async with AsyncSessionLocal() as db:
        count = await db.scalar(select(func.count()).select_from(User))
        if count and count > 0:
            return

        admin = User(
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role=UserRole.admin,
            must_change_password=True,
            created_by="system",
        )
        db.add(admin)
        await db.commit()
        logger.warning(
            "No users found - created default admin account '%s'. "
            "You MUST log in and set a new password immediately.",
            settings.ADMIN_USERNAME,
        )
