from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Network(Base):
    """
    A logical grouping of CPEs under a ManagementRouter - e.g. one per tower,
    one per client subnet/VLAN, one per neighborhood. Purely organizational;
    discovery can auto-create one per subnet it finds, or you can create them
    by hand and assign CPEs into them.
    """

    __tablename__ = "networks"

    id: Mapped[int] = mapped_column(primary_key=True)
    management_router_id: Mapped[int] = mapped_column(ForeignKey("management_routers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    cidr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vlan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    management_router: Mapped["ManagementRouter"] = relationship(back_populates="networks")  # noqa: F821
    cpes: Mapped[list["CPE"]] = relationship(back_populates="network", cascade="all, delete-orphan")  # noqa: F821
