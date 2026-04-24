# Репозиторий: сессия, одна декларативная модель, точка входа Query.
from __future__ import annotations

import datetime
import enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, inspect
from sqlalchemy.exc import InvalidRequestError, NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession

from queryforge.audit import build_event, emit_audit_event
from queryforge.exceptions import EntityNotFound
from queryforge.query import Query
from queryforge.soft_delete import has_soft_delete, soft_delete_in_db

M = TypeVar("M", bound=Any)


def _id_for_audit(instance: Any) -> Any:
    try:
        st = inspect(instance, raiseerr=True)
    except NoInspectionAvailable:
        st = None
    else:
        idt = getattr(st, "identity", None)
        if idt is not None and len(idt) == 1:
            return idt[0]
        if idt is not None and len(idt) > 1:
            return idt
    m = type(instance)
    try:
        mi = inspect(m, raiseerr=True)
        pks = mi.mapper.primary_key
        if len(pks) == 1:
            k = pks[0].key
            return getattr(instance, k, None)
        if len(pks) > 1:
            return tuple(getattr(instance, c.key) for c in pks)
    except (NoInspectionAvailable, InvalidRequestError, AttributeError, TypeError):
        pass
    for name in ("id", "pk"):
        if hasattr(instance, name):
            return getattr(instance, name)
    return str(instance)


def _jsonify(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime.date | datetime.datetime) and hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, str | int | float | bool):
        return v
    if isinstance(v, enum.Enum):
        return v.value
    return str(v)


class Repository(Generic[M]):
    """Репозиторий: query(), get* и write с опциональным аудитом."""

    def __init__(self, session: AsyncSession, model: type[M]) -> None:
        self._session = session
        self._model = model

    def query(self) -> Query[M]:
        return Query(self._session, self._model)

    def from_statement(self, stmt: Select[Any]) -> Query[M]:
        return Query(self._session, self._model, from_statement=stmt, soft_mode="with_all")

    async def get(self, pk: Any) -> M:
        ent = await self._session.get(self._model, pk)
        if ent is None:
            raise EntityNotFound(f"{self._model.__name__}({pk!r})")
        if has_soft_delete(self._model) and getattr(ent, "deleted_at", None) is not None:
            raise EntityNotFound(f"{self._model.__name__}({pk!r})")
        return ent

    async def get_or_none(self, pk: Any) -> M | None:
        try:
            return await self.get(pk)
        except EntityNotFound:
            return None

    async def exists(self, *conditions: Any) -> bool:
        if not conditions:
            return await self.query().exists()
        q = self.query()
        for c in conditions:
            q = q.where(c)  # type: ignore[assignment, arg-type, misc]
        return await q.exists()

    async def add(self, entity: M) -> None:
        self._session.add(entity)
        await self._session.flush()
        eid = _id_for_audit(entity)
        await emit_audit_event(
            build_event(
                action=f"{self._model.__name__.lower()}.created",
                entity=self._model.__name__,
                entity_id=eid,
            )
        )

    async def delete(self, entity: M) -> None:
        eid = _id_for_audit(entity)
        await soft_delete_in_db(self._session, entity)
        await emit_audit_event(
            build_event(
                action=f"{self._model.__name__.lower()}.deleted",
                entity=self._model.__name__,
                entity_id=eid,
            )
        )

    async def update(self, entity: M, **values: Any) -> None:
        changes: dict[str, dict[str, Any]] = {}
        for k, v in values.items():
            if not hasattr(entity, k):
                continue
            old = getattr(entity, k)
            if old != v:
                changes[k] = {"old": _jsonify(old), "new": _jsonify(v)}
            setattr(entity, k, v)
        await self._session.flush()
        eid = _id_for_audit(entity)
        if changes:
            await emit_audit_event(
                build_event(
                    action=f"{self._model.__name__.lower()}.updated",
                    entity=self._model.__name__,
                    entity_id=eid,
                    changes=changes,
                )
            )
