# Репозиторий: сессия, одна declarative-модель, вход в Query.
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Generic, TypeVar

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from queryforge.exceptions import EntityNotFound, UnknownUpdateFieldError
from queryforge.query import Query

M = TypeVar("M", bound=Any)


class Repository(Generic[M]):
    """Repository: query(), get* and basic write operations."""

    def __init__(
        self,
        session: AsyncSession,
        model: type[M],
    ) -> None:
        self._session = session
        self._model = model

    def query(self) -> Query[M, M]:
        return Query(self._session, self._model)

    def from_statement(self, stmt: Select[Any]) -> Query[M, Any]:
        return Query(self._session, self._model, from_statement=stmt)

    async def get(self, pk: Any) -> M:
        ent = await self._session.get(self._model, pk)
        if ent is None:
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

    async def delete(self, entity: M) -> None:
        await self._session.delete(entity)
        await self._session.flush()

    async def update(self, entity: M, **values: Any) -> None:
        await self._apply_update_values(entity, values, ignore_unknown=False)

    async def update_from_dict(
        self,
        entity: M,
        payload: Mapping[str, Any],
        *,
        ignore_unknown: bool = False,
    ) -> None:
        await self._apply_update_values(entity, payload, ignore_unknown=ignore_unknown)

    async def _apply_update_values(
        self,
        entity: M,
        values: Mapping[str, Any],
        *,
        ignore_unknown: bool,
    ) -> None:
        for k, v in values.items():
            if not hasattr(entity, k):
                if not ignore_unknown:
                    msg = f"Unknown field for update(): {self._model.__name__}.{k}"
                    raise UnknownUpdateFieldError(msg)
                continue
            setattr(entity, k, v)
        await self._session.flush()
