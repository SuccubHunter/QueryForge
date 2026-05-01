# Dynamic sorting: asc/desc, from_param, default, alias, nulls, PK fallback.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Literal, TypeVar, get_args, get_origin

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import class_mapper
from sqlalchemy.sql.elements import KeyedColumnElement, UnaryExpression

from queryforge.exceptions import InvalidSortError

M = TypeVar("M")

NullsPlacement = Literal["first", "last"]


@dataclass(frozen=True, slots=True)
class _SortField:
    column: Any
    desc: bool = False
    nulls: NullsPlacement | None = None
    aliases: tuple[str, ...] = ()

    def with_direction(self, desc_override: bool) -> _SortField:
        return _SortField(
            column=self.column,
            desc=desc_override,
            nulls=self.nulls,
            aliases=self.aliases,
        )

    def to_unary(self) -> UnaryExpression[Any] | Any:
        expr = self.column.desc() if self.desc else self.column.asc()
        if self.nulls == "first":
            return expr.nulls_first()  # type: ignore[no-any-return]
        if self.nulls == "last":
            return expr.nulls_last()  # type: ignore[no-any-return]
        return expr  # type: ignore[no-any-return]


def asc(
    column: Any,
    *,
    nulls: NullsPlacement | None = None,
    alias: str | None = None,
) -> _SortField:
    aliases = (alias,) if alias else ()
    return _SortField(column=column, desc=False, nulls=nulls, aliases=aliases)


def desc(
    column: Any,
    *,
    nulls: NullsPlacement | None = None,
    alias: str | None = None,
) -> _SortField:
    aliases = (alias,) if alias else ()
    return _SortField(column=column, desc=True, nulls=nulls, aliases=aliases)


def _sortset_orm_model(cls: type[Any]) -> type[Any] | None:
    for base in getattr(cls, "__orig_bases__", ()):
        origin = get_origin(base)
        if origin is None:
            continue
        if getattr(origin, "__name__", None) not in ("SortSet", "SortSetBase"):
            continue
        args = get_args(base)
        if len(args) >= 1 and isinstance(args[0], type):
            return args[0]
    for b in cls.__bases__:
        if isinstance(b, type) and b not in (object, SortSetBase, SortSet):
            m = _sortset_orm_model(b)
            if m is not None:
                return m
    return None


def _primary_key_columns(model: type[Any]) -> list[Any]:
    try:
        mapper = class_mapper(model)
    except (InvalidRequestError, TypeError, AttributeError):
        return []
    return list(mapper.primary_key)


class SortSetBase(Generic[M]):
    """Base class for a declarative sort set."""

    _sorts: ClassVar[dict[str, _SortField]]
    _sort_alias_to_canonical: ClassVar[dict[str, str]]
    __default_sort__: ClassVar[str | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        sorts: dict[str, _SortField] = {}
        alias_to_canonical: dict[str, str] = {}
        taken_aliases: set[str] = set()

        for n, v in cls.__dict__.items():
            if n.startswith("_"):
                continue
            if not isinstance(v, _SortField):
                continue
            if n in taken_aliases:
                msg = f"Sort field name conflicts with alias: {n!r}"
                raise InvalidSortError(msg)
            sorts[n] = v
            taken_aliases.add(n)
            for a in v.aliases:
                if not a or a in sorts or a in taken_aliases:
                    msg = f"Duplicate or empty sort alias: {a!r} (field {n!r})"
                    raise InvalidSortError(msg)
                alias_to_canonical[a] = n
                taken_aliases.add(a)

        cls._sorts = sorts
        cls._sort_alias_to_canonical = alias_to_canonical

    @classmethod
    def _resolve_sort_field(cls, name: str) -> _SortField:
        if name in cls._sorts:
            return cls._sorts[name]
        canon = cls._sort_alias_to_canonical.get(name)
        if canon is not None:
            return cls._sorts[canon]
        msg = f"Unknown sort field: {name!r}. Available: {sorted(cls._sorts)}"
        raise InvalidSortError(msg)

    @classmethod
    def _pk_tiebreakers(cls, used_columns: set[Any]) -> list[Any]:
        model = _sortset_orm_model(cls)
        if model is None:
            return []
        out: list[Any] = []
        for pk in _primary_key_columns(model):
            if pk in used_columns:
                continue
            out.append(pk.asc())  # type: ignore[union-attr]
            used_columns.add(pk)
        return out

    @classmethod
    def from_param(cls, param: str) -> list[Any]:
        """Parse ``sort`` query: ``-created_at,email`` (multiple comma-separated fields).

        An empty string uses :py:attr:`__default_sort__` when configured.
        Model primary-key columns are appended as tie breakers when missing from the chain.
        """
        raw = (param or "").strip()
        if not raw:
            raw = (getattr(cls, "__default_sort__", None) or "").strip()

        if not raw:
            return cls._pk_tiebreakers(set())

        parts = [x.strip() for x in raw.split(",") if x.strip()]
        if not parts:
            return cls._pk_tiebreakers(set())

        used: set[Any] = set()
        out: list[Any] = []
        for part in parts:
            desc_flag = part.startswith("-")
            name = part[1:] if desc_flag else part
            field = cls._resolve_sort_field(name)
            direction = True if desc_flag else field.desc
            expr = field.with_direction(direction).to_unary()
            used.add(field.column)
            out.append(expr)

        out.extend(cls._pk_tiebreakers(used))
        return out


def sort_expressions(
    sset: type[SortSetBase[M]], *names: str
) -> list[UnaryExpression[Any] | KeyedColumnElement[Any] | Any]:
    """Build ``order_by`` expressions by field names."""
    if not names:
        return sset.from_param("")
    return sset.from_param(",".join(names))


class SortSet(SortSetBase[M]):
    pass
