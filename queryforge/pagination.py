# Пагинация: Page[T] и вспомогательные вычисления.
from __future__ import annotations

import math
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Срез выборки с метаданными пагинации (совместимо с JSON из README)."""

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
        safe_size = max(1, int(size))
        safe_page = max(1, int(page))
        pages = int(math.ceil(total / safe_size)) if total > 0 else 0
        if pages > 0 and safe_page > pages:
            safe_page = pages
        return cls(  # type: ignore[return-value, arg-type, misc]
            items=items, total=total, page=safe_page, size=safe_size, pages=pages
        )


def offset_for_page(page: int, size: int) -> int:
    safe_size = max(1, int(size))
    safe_page = max(1, int(page))
    return (safe_page - 1) * safe_size
