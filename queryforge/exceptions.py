# Публичные исключения библиотеки.
from __future__ import annotations


class QueryForgeError(Exception):
    """Базовая ошибка QueryForge."""


class EntityNotFound(QueryForgeError, LookupError):
    """Сущность не найдена (например, по первичному ключу)."""
