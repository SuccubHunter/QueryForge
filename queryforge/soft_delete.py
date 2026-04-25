# Мягкое удаление: deleted_at, deleted_by, delete_reason; restore / hard delete.
from __future__ import annotations

import datetime
import uuid
from collections.abc import Awaitable, Callable
from typing import ClassVar, Literal, cast

from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, QueryableAttribute, mapped_column
from sqlalchemy.sql import ColumnElement

from queryforge.exceptions import AlreadySoftDeleted, NotSoftDeleted

# Режим фильтрации в запросе
SoftDeleteMode = Literal["default", "with_all", "only_deleted"]

SoftDeletePolicyOp = Literal["soft_delete", "restore", "hard_delete"]
SoftDeletePolicy = Callable[[SoftDeletePolicyOp, type, object], Awaitable[None] | None]

_soft_delete_policy: SoftDeletePolicy | None = None


def set_soft_delete_policy(fn: SoftDeletePolicy | None) -> None:
    """Глобальная policy для soft/restore/hard delete во всех репозиториях."""
    global _soft_delete_policy
    _soft_delete_policy = fn


def get_soft_delete_policy() -> SoftDeletePolicy | None:
    return _soft_delete_policy


class SoftDeleteMixin:
    """Мягкое удаление: deleted_at None — активна; deleted_by, delete_reason — метаданные."""

    __tablename__: ClassVar[str]  # noqa: PIE794 — mixin без DeclarativeBase
    # noqa: PIE794 — колонка в реальном Base
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None, index=True
    )
    deleted_by: Mapped[str | None] = mapped_column(
        String(64), nullable=True, default=None, index=True
    )
    delete_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)


def has_soft_delete(model: type) -> bool:
    return hasattr(model, "deleted_at")


def is_soft_deleted(instance: object) -> bool:
    if not has_soft_delete(type(instance)):
        return False
    return getattr(instance, "deleted_at", None) is not None


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


def _as_deleted_by_str(v: str | int | bool | uuid.UUID | None) -> str | None:
    if v is None:
        return None
    return str(v)


async def _run_soft_delete_policy(op: SoftDeletePolicyOp, model: type, instance: object) -> None:
    fn = get_soft_delete_policy()
    if fn is None:
        return
    r = fn(op, model, instance)
    if r is not None and hasattr(r, "__await__"):
        await r


def _set_soft_delete_fields(
    instance: object,
    *,
    at: datetime.datetime,
    deleted_by: str | int | float | bool | uuid.UUID | None,
    delete_reason: str | None,
) -> None:
    instance.deleted_at = at
    instance.deleted_by = _as_deleted_by_str(deleted_by)
    instance.delete_reason = delete_reason


def _clear_soft_delete_fields(instance: object) -> None:
    instance.deleted_at = None
    instance.deleted_by = None
    instance.delete_reason = None


async def mark_soft_deleted(
    session: AsyncSession,
    instance: object,
    *,
    at: datetime.datetime | None = None,
    deleted_by: str | int | bool | uuid.UUID | None = None,
    delete_reason: str | None = None,
) -> None:
    if not has_soft_delete(type(instance)):
        return
    if is_soft_deleted(instance):
        raise AlreadySoftDeleted("Запись уже мягко удалена")
    ts = at or datetime.datetime.now(datetime.UTC)
    await _run_soft_delete_policy("soft_delete", type(instance), instance)
    _set_soft_delete_fields(instance, at=ts, deleted_by=deleted_by, delete_reason=delete_reason)
    await session.flush()


async def restore_soft_deleted(session: AsyncSession, instance: object) -> None:
    if not has_soft_delete(type(instance)):
        msg = f"{type(instance).__name__} не поддерживает мягкое удаление"
        raise NotSoftDeleted(msg)
    if not is_soft_deleted(instance):
        raise NotSoftDeleted("Запись не в состоянии мягкого удаления")
    await _run_soft_delete_policy("restore", type(instance), instance)
    _clear_soft_delete_fields(instance)
    await session.flush()


async def hard_delete_in_db(session: AsyncSession, instance: object) -> None:
    """Безвозвратное удаление строки (DELETE)."""
    await _run_soft_delete_policy("hard_delete", type(instance), instance)
    await session.delete(instance)
    await session.flush()


async def soft_delete_in_db(
    session: AsyncSession,
    instance: object,
    *,
    deleted_by: str | int | bool | uuid.UUID | None = None,
    delete_reason: str | None = None,
) -> None:
    col = _deleted_at_column(type(instance))
    if col is None:
        await hard_delete_in_db(session, instance)
        return
    await mark_soft_deleted(
        session,
        instance,
        deleted_by=deleted_by,
        delete_reason=delete_reason,
    )
