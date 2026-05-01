# Pydantic: имена полей совпадают с атрибутами User для project().
from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, ConfigDict
from queryforge import FilterSet, SortSet, asc, contains, desc, eq, gte
from queryforge.fastapi import query_params_annotated

from app.models import User, UserStatus


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    age: int
    status: UserStatus
    created_at: datetime.datetime


class UserEmailRead(BaseModel):
    id: uuid.UUID
    email: str


class UserUpdate(BaseModel):
    email: str | None = None
    age: int | None = None
    status: UserStatus | None = None


class UserFilters(FilterSet[User]):
    status: UserStatus | None = eq(User.status)
    min_age: int | None = gte(User.age)
    email: str | None = contains(User.email)


class UserSorts(SortSet[User]):
    __default_sort__ = "-created_at"
    email = asc(User.email)
    age = asc(User.age)
    created_at = desc(User.created_at, alias="created")


UserListQuery = query_params_annotated(UserFilters, UserSorts)
