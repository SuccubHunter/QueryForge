# Тестовые declarative-модели и DTO.
from __future__ import annotations

import datetime
import enum
import uuid

from pydantic import BaseModel
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(128))
    user: Mapped[User] = relationship(back_populates="orders")


class Profile(Base):
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    bio: Mapped[str] = mapped_column(String(256))
    user: Mapped[User] = relationship(back_populates="profile")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255))
    age: Mapped[int] = mapped_column()
    status: Mapped[UserStatus] = mapped_column(String(32))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    # lazy=raise проверяет, что Query действительно включает eager-loading.
    orders: Mapped[list[Order]] = relationship(
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
    )
    profile: Mapped[Profile | None] = relationship(
        back_populates="user",
        uselist=False,
        lazy="raise",
        cascade="all, delete-orphan",
    )


class UserRead(BaseModel):
    id: uuid.UUID
    email: str
    status: UserStatus
    created_at: datetime.datetime


class ProfileRead(BaseModel):
    bio: str


class OrderRead(BaseModel):
    title: str


class UserDetailedRead(BaseModel):
    id: uuid.UUID
    email: str
    profile: ProfileRead | None
    orders: list[OrderRead]
