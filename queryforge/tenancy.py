# Multi-tenancy: TenantContext, TenantMixin, интеграция с Query/Repository.
from __future__ import annotations

import contextvars
import uuid
from typing import ClassVar

from sqlalchemy import Uuid
from sqlalchemy.orm import Mapped, mapped_column

_tenant_id_var: contextvars.ContextVar[uuid.UUID | str | int | None] = contextvars.ContextVar(
    "queryforge_tenant_id",
    default=None,
)


def get_tenant_id() -> uuid.UUID | str | int | None:
    """Текущий tenant_id из ``TenantContext`` (или ``None`` вне контекста)."""
    return _tenant_id_var.get()


class TenantContext:
    """Асинхронный контекст: ``async with TenantContext(tenant_id=...):``."""

    def __init__(self, tenant_id: uuid.UUID | str | int) -> None:
        self.tenant_id = tenant_id
        self._token: contextvars.Token[uuid.UUID | str | int | None] | None = None

    async def __aenter__(self) -> TenantContext:
        self._token = _tenant_id_var.set(self.tenant_id)
        return self

    async def __aexit__(self, _exc_type: object, _exc: object, _tb: object) -> None:
        if self._token is not None:
            _tenant_id_var.reset(self._token)


def has_tenant(model: type) -> bool:
    """Модель объявляет колонку ``tenant_id`` (например через ``TenantMixin``)."""
    return hasattr(model, "tenant_id")


class TenantMixin:
    """Изоляция по арендатору: обязательная колонка ``tenant_id``."""

    __tablename__: ClassVar[str]  # noqa: PIE794 — mixin без DeclarativeBase
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
