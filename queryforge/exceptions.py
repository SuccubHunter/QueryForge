# Публичные исключения библиотеки.
from __future__ import annotations


class QueryForgeError(Exception):
    """Базовая ошибка QueryForge."""


class EntityNotFound(QueryForgeError, LookupError):
    """Сущность не найдена (например, по первичному ключу)."""


class AlreadySoftDeleted(QueryForgeError, RuntimeError):
    """Повторное мягкое удаление уже удалённой записи."""


class NotSoftDeleted(QueryForgeError, RuntimeError):
    """Восстановление записи, которая не была мягко удалена."""


class MissingTenantError(QueryForgeError, RuntimeError):
    """Нет tenant_id в контексте или не задан for_tenant() для tenant-scoped модели."""


class MissingPolicyError(QueryForgeError, RuntimeError):
    """Нет `read_scope` в `Repository` — передайте политику по умолчанию для `visible_for()`."""


class ProjectionError(QueryForgeError, ValueError):
    """project()/into() не сопоставил DTO с колонками ORM (strict, смысл полей, nested)."""

    def __init__(
        self,
        message: str,
        *,
        dto_name: str | None = None,
        field_name: str | None = None,
        unmapped_fields: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.dto_name = dto_name
        self.field_name = field_name
        self.unmapped_fields = unmapped_fields
