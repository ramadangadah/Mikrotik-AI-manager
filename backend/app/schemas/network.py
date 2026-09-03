from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class NetworkCreate(BaseModel):
    management_router_id: int
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    cidr: str | None = None
    vlan_id: int | None = None


class NetworkUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cidr: str | None = None
    vlan_id: int | None = None


class NetworkOut(BaseModel):
    id: int
    management_router_id: int
    name: str
    description: str | None
    cidr: str | None
    vlan_id: int | None
    created_at: datetime
    cpe_count: int = 0

    model_config = {"from_attributes": True}
