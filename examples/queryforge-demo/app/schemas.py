# Pydantic: имена полей = атрибуты User, используемые в project
from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models import UserStatus


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    status: UserStatus
    created_at: datetime.datetime


class UserListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)
    status: UserStatus | None = None
    min_age: int | None = Field(default=None, ge=0)
