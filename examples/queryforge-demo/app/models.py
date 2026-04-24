# ORM: таблица users совпадает с docker/initdb/00-schema.sql
from __future__ import annotations

import datetime
import enum
import uuid
from typing import ClassVar

from queryforge import SoftDeleteMixin
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class User(SoftDeleteMixin, Base):
    __tablename__: ClassVar[str] = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    age: Mapped[int] = mapped_column()
    status: Mapped[UserStatus] = mapped_column(String(32))
    created_at: Mapped[datetime.datetime] = mapped_column(
        default=datetime.datetime.now(datetime.UTC)
    )
