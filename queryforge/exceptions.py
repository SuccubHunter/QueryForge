# Публичные исключения библиотеки.
from __future__ import annotations


class QueryForgeError(Exception):
    """Base QueryForge error."""


class EntityNotFound(QueryForgeError, LookupError):
    """Entity not found, for example by primary key."""


class ProjectionError(QueryForgeError, ValueError):
    """DTO projection failed to map DTO fields to ORM columns."""

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


class InvalidQueryStateError(QueryForgeError, RuntimeError):
    """Query was built into an invalid state for the selected result shape."""


class InvalidSortError(QueryForgeError, ValueError):
    """Invalid sort parameter or SortSet declaration."""


class InvalidPaginationError(QueryForgeError, ValueError):
    """Invalid page/size parameters."""


class UnknownUpdateFieldError(QueryForgeError, AttributeError):
    """Repository.update/update_from_dict received a field missing from the ORM entity."""
