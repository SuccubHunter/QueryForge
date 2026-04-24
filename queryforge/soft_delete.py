# Мягкое удаление: колонка deleted_at, None — запись не удалена.
from __future__ import annotations

import datetime
from typing import ClassVar, Literal, cast

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, QueryableAttribute, mapped_column
from sqlalchemy.sql import ColumnElement

# Режим фильтрации в запросе
SoftDeleteMode = Literal["default", "with_all", "only_deleted"]


class SoftDeleteMixin:
    """Колонка мягкого удаления. deleted_at is None — запись активна."""

    __tablename__: ClassVar[str]  # объявляется в дочерней декларативной модели
    # noqa: PIE794 — mixin без DeclarativeBase, колонка добавляется в реальный Base
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )


def has_soft_delete(model: type) -> bool:
    return hasattr(model, "deleted_at")


def _deleted_at_column(
    model: type,
) -> QueryableAttribute[datetime.datetime | None] | None:
    if not has_soft_delete(model):
        return None
    c = cast("QueryableAttribute[datetime.datetime | None]", model.deleted_at)
    return c


def soft_delete_clause_for_mode(model: type, mode: SoftDeleteMode) -> list[ColumnElement[bool]]:
    col = _deleted_at_column(model)
    if col is None:
        return []
    if mode == "default":
        return [col.is_(None)]
    if mode == "with_all":
        return []
    if mode == "only_deleted":
        return [col.is_not(None)]
    return []


async def mark_soft_deleted(
    session: AsyncSession, instance: object, *, at: datetime.datetime | None = None
) -> None:
    if not has_soft_delete(type(instance)):
        return
    ts = at or datetime.datetime.now(datetime.UTC)
    instance.deleted_at = ts
    await session.flush()


async def soft_delete_in_db(session: AsyncSession, instance: object) -> None:
    col = _deleted_at_column(type(instance))
    if col is None:
        await session.delete(instance)
        await session.flush()
        return
    await mark_soft_deleted(session, instance)
