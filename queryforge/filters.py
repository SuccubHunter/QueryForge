# Наборы фильтров: декларативные eq/gte/contains и применение к Query.
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, cast

from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql import ColumnElement

M = TypeVar("M")


@dataclass
class _FilterOp(ABC):
    @abstractmethod
    def build(self, value: Any) -> ColumnElement[bool]: ...


@dataclass
class _Eq(_FilterOp):
    column: Any

    def build(self, value: Any) -> ColumnElement[bool]:
        return cast("ColumnElement[bool]", self.column == value)


@dataclass
class _Gte(_FilterOp):
    column: Any

    def build(self, value: Any) -> ColumnElement[bool]:
        return cast("ColumnElement[bool]", self.column >= value)


@dataclass
class _Lte(_FilterOp):
    column: Any

    def build(self, value: Any) -> ColumnElement[bool]:
        return cast("ColumnElement[bool]", self.column <= value)


@dataclass
class _IlikeContains(_FilterOp):
    """Подстрока: ILIKE %value% (для str); для Enum — по str(value).value."""

    column: InstrumentedAttribute[Any] | Any

    def build(self, value: Any) -> ColumnElement[bool]:
        v = f"%{value.value}%" if isinstance(value, Enum) else f"%{value!s}%"
        return cast("ColumnElement[bool]", self.column.ilike(v))


def eq(column: Any) -> _Eq:
    return _Eq(column=column)


def gte(column: Any) -> _Gte:
    return _Gte(column=column)


def lte(column: Any) -> _Lte:
    return _Lte(column=column)


def contains(column: Any) -> _IlikeContains:
    return _IlikeContains(column=column)


class FilterSetBase(Generic[M]):
    """Собирает eq/gte/contains из тела подкласса в _filter_ops."""

    _filter_ops: dict[str, _FilterOp]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        ops: dict[str, _FilterOp] = {}
        for n, v in cls.__dict__.items():
            if n.startswith("_") or n == "model_config":
                continue
            if isinstance(v, _FilterOp):
                ops[n] = v
        cls._filter_ops = ops

    def __init__(self, **data: Any) -> None:
        for n in self._filter_ops:
            if n in data:
                object.__setattr__(self, n, data[n])
            else:
                object.__setattr__(self, n, None)

    def _non_null_wheres(self) -> list[ColumnElement[bool]]:
        w: list[ColumnElement[bool]] = []
        for name, op in self._filter_ops.items():
            v = getattr(self, name, None)
            if v is not None:
                w.append(op.build(v))
        return w


class FilterSet(FilterSetBase[M]):
    """Пользователь: class UserFilters(FilterSet[User]): status = eq(User.status) ..."""

    pass
