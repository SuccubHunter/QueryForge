# Репозиторий: сессия, одна декларативная модель, точка входа Query.
from __future__ import annotations

import datetime
import enum
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, inspect
from sqlalchemy.exc import InvalidRequestError, NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession

from queryforge.audit import build_event, get_audit_context, schedule_audit_event
from queryforge.exceptions import (
    EntityNotFound,
    MissingTenantError,
    NotSoftDeleted,
    QueryForgeError,
)
from queryforge.policy import ReadScope
from queryforge.query import Query
from queryforge.soft_delete import (
    hard_delete_in_db,
    has_soft_delete,
    restore_soft_deleted,
    soft_delete_in_db,
)
from queryforge.tenancy import get_tenant_id, has_tenant

M = TypeVar("M", bound=Any)


def _assert_current_tenant(model: type[Any], entity: Any) -> None:
    if not has_tenant(model):
        return
    ctx = get_tenant_id()
    if ctx is None:
        msg = f"Для операций с {model.__name__} нужен TenantContext"
        raise MissingTenantError(msg)
    if getattr(entity, "tenant_id", None) != ctx:
        raise EntityNotFound(f"{model.__name__} не в текущем tenant")


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


def _entity_column_snapshot(instance: Any) -> dict[str, Any]:
    """Снимок mapped-колонок для аудита (old/new)."""
    try:
        st = inspect(instance, raiseerr=True)
        mapper = getattr(st, "mapper", None)
    except (NoInspectionAvailable, InvalidRequestError, TypeError, AttributeError):
        return {"value": str(instance)}
    if mapper is None:
        return {"value": str(instance)}
    out: dict[str, Any] = {}
    for col in mapper.column_attrs:
        key = col.key
        if key.startswith("_"):
            continue
        out[key] = _jsonify(getattr(instance, key, None))
    return out


class Repository(Generic[M]):
    """Репозиторий: query(), get* и write с опциональным аудитом.

    ``read_scope`` задаёт политику по умолчанию для ``query().visible_for(user)``; к ``get`` /
    ``get_or_none`` не применяется (по PK — отдельные проверки прав в приложении).
    """

    def __init__(
        self,
        session: AsyncSession,
        model: type[M],
        *,
        read_scope: ReadScope | None = None,
    ) -> None:
        self._session = session
        self._model = model
        self._read_scope = read_scope

    def query(self) -> Query[M, M]:
        return Query(self._session, self._model, read_scope=self._read_scope)

    def from_statement(self, stmt: Select[Any]) -> Query[M, Any]:
        return Query(
            self._session,
            self._model,
            from_statement=stmt,
            soft_mode="with_all",
            read_scope=self._read_scope,
        )

    async def get(self, pk: Any) -> M:
        ent = await self._session.get(self._model, pk)
        if ent is None:
            raise EntityNotFound(f"{self._model.__name__}({pk!r})")
        if has_soft_delete(self._model) and getattr(ent, "deleted_at", None) is not None:
            raise EntityNotFound(f"{self._model.__name__}({pk!r})")
        if has_tenant(self._model):
            ctx = get_tenant_id()
            if ctx is None:
                msg = f"Для get() tenant-scoped сущности {self._model.__name__} нужен TenantContext"
                raise MissingTenantError(msg)
            if getattr(ent, "tenant_id", None) != ctx:
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
        if has_tenant(self._model):
            tid = getattr(entity, "tenant_id", None)
            if tid is None:
                ctx = get_tenant_id()
                if ctx is None:
                    msg = f"Укажите {self._model.__name__}.tenant_id или TenantContext"
                    raise MissingTenantError(msg)
                entity.tenant_id = ctx  # type: ignore[union-attr]
            else:
                ctx = get_tenant_id()
                if ctx is not None and tid != ctx:
                    raise EntityNotFound(
                        f"{self._model.__name__}: tenant_id не совпадает с контекстом"
                    )
        self._session.add(entity)
        await self._session.flush()
        eid = _id_for_audit(entity)
        snap = _entity_column_snapshot(entity)
        await schedule_audit_event(
            self._session,
            build_event(
                action=f"{self._model.__name__.lower()}.created",
                entity=self._model.__name__,
                entity_id=eid,
                snapshot={"old": None, "new": snap},
            ),
        )

    async def delete(
        self,
        entity: M,
        *,
        reason: str | None = None,
        deleted_by: str | int | bool | UUID | None = None,
    ) -> None:
        _assert_current_tenant(self._model, entity)
        eid = _id_for_audit(entity)
        ctx = get_audit_context()
        old_snap = _entity_column_snapshot(entity)
        eff_by = deleted_by if deleted_by is not None else ctx.actor_id
        eff_reason = reason if reason is not None else ctx.reason
        await soft_delete_in_db(
            self._session,
            entity,
            deleted_by=eff_by,
            delete_reason=eff_reason,
        )
        await schedule_audit_event(
            self._session,
            build_event(
                action=f"{self._model.__name__.lower()}.deleted",
                entity=self._model.__name__,
                entity_id=eid,
                reason=eff_reason,
                snapshot={"old": old_snap, "new": None},
            ),
        )

    async def restore(self, entity: M) -> None:
        _assert_current_tenant(self._model, entity)
        eid = _id_for_audit(entity)
        if not has_soft_delete(self._model):
            msg = f"{self._model.__name__} не поддерживает мягкое удаление"
            raise NotSoftDeleted(msg)
        old_snap = _entity_column_snapshot(entity)
        await restore_soft_deleted(self._session, entity)
        new_snap = _entity_column_snapshot(entity)
        await schedule_audit_event(
            self._session,
            build_event(
                action=f"{self._model.__name__.lower()}.restored",
                entity=self._model.__name__,
                entity_id=eid,
                snapshot={"old": old_snap, "new": new_snap},
            ),
        )

    async def hard_delete(self, entity: M) -> None:
        _assert_current_tenant(self._model, entity)
        eid = _id_for_audit(entity)
        old_snap = _entity_column_snapshot(entity)
        await hard_delete_in_db(self._session, entity)
        await schedule_audit_event(
            self._session,
            build_event(
                action=f"{self._model.__name__.lower()}.hard_deleted",
                entity=self._model.__name__,
                entity_id=eid,
                snapshot={"old": old_snap, "new": None},
            ),
        )

    async def update(self, entity: M, *, strict: bool = True, **values: Any) -> None:
        _assert_current_tenant(self._model, entity)
        if has_tenant(self._model) and "tenant_id" in values:
            msg = f"Поле tenant_id нельзя менять через update() для {self._model.__name__}"
            raise QueryForgeError(msg)
        changes: dict[str, dict[str, Any]] = {}
        for k, v in values.items():
            if not hasattr(entity, k):
                if strict:
                    msg = f"Неизвестное поле для update(): {self._model.__name__}.{k}"
                    raise QueryForgeError(msg)
                continue
            old = getattr(entity, k)
            if old != v:
                changes[k] = {"old": _jsonify(old), "new": _jsonify(v)}
            setattr(entity, k, v)
        await self._session.flush()
        eid = _id_for_audit(entity)
        if changes:
            await schedule_audit_event(
                self._session,
                build_event(
                    action=f"{self._model.__name__.lower()}.updated",
                    entity=self._model.__name__,
                    entity_id=eid,
                    changes=changes,
                ),
            )
