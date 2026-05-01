# Pagination: Page[T] and helper calculations.
from __future__ import annotations

import math
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from queryforge.exceptions import InvalidPaginationError

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Result slice with pagination metadata, compatible with the README JSON shape."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        from_attributes=True,
    )

    items: list[T] = Field(default_factory=list)  # type: ignore[valid-type]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    size: int = Field(ge=1)
    pages: int = Field(ge=0)

    @classmethod
    def from_items(
        cls,
        items: list[T],
        *,
        total: int,
        page: int,
        size: int,
    ) -> Page[T]:
        safe_page, safe_size = validate_page_size(page, size)
        pages = int(math.ceil(total / safe_size)) if total > 0 else 0
        return cls(  # type: ignore[return-value, arg-type, misc]
            items=items,
            total=total,
            page=safe_page,
            size=safe_size,
            pages=pages,
        )


def validate_page_size(page: int, size: int) -> tuple[int, int]:
    try:
        safe_page = int(page)
    except (TypeError, ValueError, OverflowError) as e:
        raise InvalidPaginationError("page must be an integer") from e
    try:
        safe_size = int(size)
    except (TypeError, ValueError, OverflowError) as e:
        raise InvalidPaginationError("size must be an integer") from e
    if safe_page < 1:
        raise InvalidPaginationError("page must be greater than or equal to 1")
    if safe_size < 1:
        raise InvalidPaginationError("size must be greater than or equal to 1")
    return safe_page, safe_size


def offset_for_page(page: int, size: int) -> int:
    safe_page, safe_size = validate_page_size(page, size)
    return (safe_page - 1) * safe_size
