from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppSetting(Base):
    """
    Simple key/value overrides editable from the Settings screen at runtime -
    LLM provider/key, notification webhooks, ML toggle - without needing to
    edit the .env file and restart the container. Infra-level settings
    (DB URL, port, JWT secret) stay in .env on purpose; those are not here.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
