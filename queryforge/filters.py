# Filter sets: declarative eq/gte/contains and Pydantic validation.
from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Generic,
    TypeVar,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.sql import ColumnElement
from typing_extensions import TypeIs

M = TypeVar("M")

# --- Filter operations (field declarations) ------------------------------------


@dataclass
class _FilterOp(ABC):
    column: Any

    @abstractmethod
    def build(self, value: Any) -> ColumnElement[bool]: ...


@dataclass
class _Eq(_FilterOp):
    def build(self, value: Any) -> ColumnElement[bool]:
        return cast("ColumnElement[bool]", self.column == value)


@dataclass
class _Gte(_FilterOp):
    def build(self, value: Any) -> ColumnElement[bool]:
        return cast("ColumnElement[bool]", self.column >= value)


@dataclass
class _Lte(_FilterOp):
    def build(self, value: Any) -> ColumnElement[bool]:
        return cast("ColumnElement[bool]", self.column <= value)


@dataclass
class _IlikeContains(_FilterOp):
    """Substring search: ILIKE %value% for str; Enum uses value.value in the pattern."""

    def build(self, value: Any) -> ColumnElement[bool]:
        v = f"%{value.value}%" if isinstance(value, Enum) else f"%{value!s}%"
        return cast("ColumnElement[bool]", self.column.ilike(v))


def _is_filter_op(x: object) -> TypeIs[_FilterOp]:
    return isinstance(x, _FilterOp)


def eq(column: Any) -> Any:
    return _Eq(column=column)


def gte(column: Any) -> Any:
    return _Gte(column=column)


def lte(column: Any) -> Any:
    return _Lte(column=column)


def contains(column: Any) -> Any:
    return _IlikeContains(column=column)


def _is_union_including_none(ann: Any) -> bool:
    try:
        ag = get_args(ann) if (get_args(ann) is not None) else ()
    except (TypeError, ValueError):
        return False
    return type(None) in ag


def _ensure_optional(ann: Any) -> Any:
    """Makes a field optional for Pydantic: ``T | None``."""
    if ann is None:
        return Any | None
    o = get_origin(ann)
    if o is not None and getattr(o, "__name__", None) == "Mapped":
        inner = get_args(ann)
        return _ensure_optional(inner[0]) if inner else _ensure_optional(Any)
    if _is_union_including_none(ann):
        return ann
    try:
        return ann | type(None)  # type: ignore[operator,return-value]
    except TypeError:
        return Any | None


def _get_declarative_type_hints(model_t: type[Any]) -> dict[str, Any]:
    try:
        mod = importlib.import_module(model_t.__module__)
    except (ImportError, ValueError, TypeError):
        return get_type_hints(model_t, include_extras=True)
    try:
        return get_type_hints(
            model_t,
            localns=vars(mod),
            include_extras=True,
        )
    except (NameError, TypeError, ValueError, KeyError, SyntaxError, AttributeError):
        return {}


def _filter_field_annotation_from_samodel(model_t: type[Any], col_attr: Any) -> Any:
    """Type from ``Mapped[T]`` on the ORM model -> ``T | None`` through ``get_type_hints``."""
    try:
        key = col_attr.key
    except (AttributeError, TypeError):
        return _ensure_optional(Any)
    hints = _get_declarative_type_hints(model_t)
    st = hints.get(key)
    if st is None:
        return _ensure_optional(Any)
    origin = get_origin(st)
    if origin is not None and getattr(origin, "__name__", None) == "Mapped":
        t_in = get_args(st)
        if t_in:
            return _ensure_optional(t_in[0])
    return _ensure_optional(st)


def _pydantic_filterset_type_arg(base: type) -> type[Any] | None:
    """Pydantic v2: ``FilterSet[User]`` is a concrete class, not ``typing.GenericAlias``."""
    meta = getattr(base, "__pydantic_generic_metadata__", None) or {}
    origin = meta.get("origin")
    if origin is not None and getattr(origin, "__name__", None) == "FilterSet":
        g_args = meta.get("args") or ()
        if len(g_args) == 1 and isinstance(g_args[0], type):
            return g_args[0]  # type: ignore[return-value]
    return None


def _get_declared_orm(bases: tuple[Any, ...]) -> type[Any] | None:
    for b in bases:
        o = get_origin(b)
        if o is not None and getattr(o, "__name__", None) == "FilterSet":
            a = get_args(b)
            if a and isinstance(a[0], type):
                return a[0]  # type: ignore[return-value]
    for b in bases:
        if isinstance(b, type) and b is not object:
            m = _pydantic_filterset_type_arg(b)
            if m is not None:
                return m
    for b in bases:
        if isinstance(b, type) and getattr(b, "declared_orm_model", None) is not None:
            dm = b.declared_orm_model
            if isinstance(dm, type):
                return dm
    return None


def _inherited_filter_ops(bases: tuple[Any, ...]) -> dict[str, _FilterOp]:
    out: dict[str, _FilterOp] = {}
    for b in bases:
        if isinstance(b, type) and issubclass(b, BaseModel):
            p = getattr(b, "__queryforge_filter_ops__", None)
            if isinstance(p, dict):
                out.update(p)
    return out


_FilterModelMeta = type(BaseModel)


class _FilterSetMeta(_FilterModelMeta):
    def __new__(  # type: ignore[no-untyped-def]
        mcs,
        name: str,
        bases: tuple,
        namespace: dict[str, Any],
        **kwargs: Any,
    ) -> type:
        ann = {**namespace.get("__annotations__", {})}
        new_ops: dict[str, _FilterOp] = {}
        orm_model = _get_declared_orm(bases)

        skip = frozenset(
            {
                "__module__",
                "__qualname__",
                "model_config",
                "__orig_bases__",
                "__static_attributes__",
            }
        )
        for k, v in list(namespace.items()):
            if k in skip or k.startswith("__"):
                continue
            if not _is_filter_op(v):
                continue
            new_ops[k] = v
            if k not in ann:
                if orm_model is not None:
                    ann[k] = _filter_field_annotation_from_samodel(orm_model, v.column)
                else:
                    ann[k] = _ensure_optional(Any)
            elif isinstance(ann.get(k), str):
                # ``from __future__ import annotations``: string annotation; Pydantic resolves it.
                pass
            else:
                ann[k] = _ensure_optional(ann[k])
            namespace[k] = Field(default=None)

        inherited = _inherited_filter_ops(bases)
        merged_ops: dict[str, _FilterOp] = {**inherited, **new_ops}
        orm = _get_declared_orm(bases)
        orm_m: type[Any] | None = orm
        if orm_m is None:
            for b in bases:
                if isinstance(b, type) and hasattr(b, "declared_orm_model"):
                    om = b.declared_orm_model  # type: ignore[attr-defined]
                    if isinstance(om, type):
                        orm_m = om
                        break
        namespace["__annotations__"] = ann
        cls = super().__new__(mcs, name, bases, namespace, **kwargs)
        cls.__queryforge_filter_ops__ = merged_ops
        if orm_m is not None:
            cls.declared_orm_model = orm_m
        return cls


class FilterSet(BaseModel, Generic[M], metaclass=_FilterSetMeta):
    """Usage: ``class UserFilters(FilterSet[User]): s: T | None = eq(User.s)``."""

    # Not model fields (ClassVar): Pydantic does not try to validate them.
    __queryforge_filter_ops__: ClassVar[dict[str, _FilterOp]] = {}
    declared_orm_model: ClassVar[type[Any] | None] = None

    model_config = ConfigDict(extra="forbid", validate_default=True, str_strip_whitespace=True)

    def to_wheres(self) -> list[ColumnElement[bool]]:
        w: list[ColumnElement[bool]] = []
        ops: dict[str, _FilterOp] = getattr(
            self.__class__,
            "__queryforge_filter_ops__",
            {},
        )
        for name, op in ops.items():
            v = getattr(self, name, None)
            if v is not None:
                w.append(op.build(v))
        return w

    def _non_null_wheres(self) -> list[ColumnElement[bool]]:
        return self.to_wheres()


__all__ = [
    "FilterSet",
    "contains",
    "eq",
    "gte",
    "lte",
]
