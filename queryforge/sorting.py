# Динамическая сортировка: asc/desc и from_param.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy.sql.elements import KeyedColumnElement, UnaryExpression

M = TypeVar("M")


@dataclass
class _SortField:
    column: Any
    desc: bool = False

    def to_unary(self) -> UnaryExpression[Any] | Any:
        if self.desc:
            return self.column.desc()  # type: ignore[no-any-return]
        return self.column.asc()  # type: ignore[no-any-return]


def asc(column: Any) -> _SortField:
    return _SortField(column=column, desc=False)


def desc(column: Any) -> _SortField:
    return _SortField(column=column, desc=True)


class SortSetBase(Generic[M]):
    _sorts: ClassVar[dict[str, _SortField]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        sorts: dict[str, _SortField] = {}
        for n, v in cls.__dict__.items():
            if n.startswith("_"):
                continue
            if isinstance(v, _SortField):
                sorts[n] = v
        cls._sorts = sorts

    @classmethod
    def from_param(cls, param: str) -> list[Any]:
        """Одна колонка: "created_at" (asc) или "-created_at" (desc)."""
        p = (param or "").strip()
        if not p:
            return []
        desc_flag = p.startswith("-")
        name = p[1:] if desc_flag else p
        if name not in cls._sorts:
            raise ValueError(
                f"Неизвестное поле сортировки: {name!r}. Доступны: {sorted(cls._sorts)}"
            )
        s = cls._sorts[name]
        # Префикс "-" — явно убывание; иначе берём направление из desc(...)/asc(...) в SortSet
        field = _SortField(column=s.column, desc=True if desc_flag else s.desc)
        return [field.to_unary()]


def sort_expressions(
    sset: type[SortSetBase[M]], *names: str
) -> list[UnaryExpression[Any] | KeyedColumnElement[Any] | Any]:
    """Собрать order_by по нескольким именам полей SortSet (каждое как from_param)."""
    out: list[Any] = []
    for n in names:
        out.extend(sset.from_param(n))
    return out


class SortSet(SortSetBase[M]):
    pass
