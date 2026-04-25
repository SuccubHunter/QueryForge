# Backends хранения событий аудита (outbox / таблица).
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession


@runtime_checkable
class AuditStorageBackend(Protocol):
    """Запись payload в той же транзакции, что и бизнес-операция (outbox-таблица)."""

    async def append(self, session: AsyncSession, payload: Mapping[str, Any]) -> None:
        """Поставить запись (session.add; без commit)."""


class SQLAlchemyAuditStorage:
    """Outbox: ORM-модель со столбцом под JSON (``JSON`` / ``Text`` + JSON)."""

    def __init__(
        self,
        model: type[Any],
        *,
        payload_attr: str = "payload",
    ) -> None:
        self._model = model
        self._payload_attr = payload_attr

    async def append(self, session: AsyncSession, payload: Mapping[str, Any]) -> None:
        row = self._model()
        setattr(row, self._payload_attr, dict(payload))
        session.add(row)
