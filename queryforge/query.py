# Конвейер Query: where, project, paginate, terminal-методы, statement.
# pyright: strict
from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, Self, TypeVar, cast, overload

from pydantic import BaseModel
from sqlalchemy import Select, func, inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, joinedload, selectinload
from sqlalchemy.sql import ColumnElement

from queryforge.exceptions import EntityNotFound, InvalidQueryStateError
from queryforge.pagination import Page, offset_for_page, validate_page_size
from queryforge.projection import (
    ProjectionMode,
    ProjectionNested,
    entity_to_pydantic,
    pydantic_model_columns,
    row_to_pydantic,
    validate_into_columns,
)

ModelT = TypeVar("ModelT", bound=Any)
ResultT = TypeVar("ResultT", bound=Any)
DtoT = TypeVar("DtoT", bound=BaseModel)
T1 = TypeVar("T1")
T2 = TypeVar("T2")
T3 = TypeVar("T3")
T4 = TypeVar("T4")
T5 = TypeVar("T5")
T6 = TypeVar("T6")
T7 = TypeVar("T7")
T8 = TypeVar("T8")
T9 = TypeVar("T9")
T10 = TypeVar("T10")
TValue = TypeVar("TValue")

WhereInput = ColumnElement[bool] | Callable[[], ColumnElement[bool]]
ResultMode = Literal["entity", "projection", "tuple", "scalar"]


@dataclass(frozen=True, slots=True)
class JoinOp:
    """One ``Select.join`` call (args + isouter/full)."""

    args: tuple[Any, ...]
    join_kwargs: tuple[tuple[str, Any], ...] = ()

    @classmethod
    def from_join(cls, *args: Any, isouter: bool = False, full: bool = False) -> JoinOp:
        jkw: list[tuple[str, Any]] = []
        if isouter:
            jkw.append(("isouter", True))
        if full:
            jkw.append(("full", True))
        return cls(args=tuple(args), join_kwargs=tuple(jkw))


@dataclass(frozen=True, slots=True)
class QueryState:
    """Immutable Query pipeline state (where / order / limit / projection / ...)."""

    wheres: tuple[ColumnElement[bool], ...] = ()
    order: tuple[Any, ...] = ()
    limit: int | None = None
    offset: int | None = None
    raw: Select[Any] | None = None
    projection: type[BaseModel] | None = None
    explicit_cols: tuple[Any, ...] | None = None
    unwrap_scalar: bool = False
    projection_mode: ProjectionMode = "strict"
    projection_nested: ProjectionNested = "forbid"
    joins: tuple[JoinOp, ...] = ()
    loader_options: tuple[Any, ...] = ()
    result_mode: ResultMode = "entity"


def _as_where_clause(
    c: WhereInput,
) -> ColumnElement[bool]:
    if isinstance(c, ColumnElement):
        return cast("ColumnElement[bool]", c)
    if callable(c):
        return c()
    msg = f"where_if: expected ColumnElement[bool] or () -> ColumnElement, got {type(c)!r}"
    raise TypeError(msg)


class Query(Generic[ModelT, ResultT]):
    """Pipeline over select(); terminal methods run async execute.

    State is immutable: `where` / `order_by` / `limit` / `project` / `select` etc.
    return a new `Query`; the original object is not mutated. To accumulate conditions,
    use chaining or reassignment: `q = q.where(...)`.
    """

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        *,
        state: QueryState | None = None,
        from_statement: Select[Any] | None = None,
        projection: type[BaseModel] | None = None,
        _explicit_cols: tuple[Any, ...] | None = None,
        _unwrap_scalar: bool = False,
        _projection_mode: ProjectionMode = "strict",
        _projection_nested: ProjectionNested = "forbid",
    ) -> None:
        self._session = session
        self._model: type[ModelT] = model
        if state is not None:
            self._state = state
        else:
            self._state = QueryState(
                raw=from_statement,
                projection=projection,
                explicit_cols=_explicit_cols,
                unwrap_scalar=_unwrap_scalar,
                projection_mode=_projection_mode,
                projection_nested=_projection_nested,
            )

    def _all_wheres(self) -> list[ColumnElement[bool]]:
        return [*self._state.wheres]

    def _dedupe_joined_entity_rows(self) -> bool:
        st = self._state
        if st.raw is not None or not st.joins:
            return False
        if st.result_mode == "entity":
            return True
        return (
            st.result_mode == "projection"
            and st.projection is not None
            and st.explicit_cols is None
        )

    def _build_base_select(
        self, *, with_loader_options: bool = True, with_order: bool = True
    ) -> Select[Any]:
        st = self._state
        if st.raw is not None:
            s = st.raw
        elif st.explicit_cols is not None:
            s = select(*st.explicit_cols)  # type: ignore[arg-type]
        elif st.projection is not None and st.projection_nested != "orm":
            cols = pydantic_model_columns(
                self._model,
                st.projection,
                mode=st.projection_mode,
                nested=st.projection_nested,
            )
            s = select(*cols)  # type: ignore[call-overload,arg-type]
        else:
            s = select(self._model)  # type: ignore[call-overload]
        for op in st.joins:
            s = s.join(*op.args, **dict(op.join_kwargs))
        for w in self._all_wheres():
            s = s.where(w)
        if self._dedupe_joined_entity_rows():
            s = s.distinct()
        if with_order:
            for o in st.order:
                s = s.order_by(o)  # type: ignore[call-overload]
        if with_loader_options and st.loader_options:
            s = s.options(*st.loader_options)
        return s

    def _build_select_paginated(self) -> Select[Any]:
        s = self._build_base_select()
        st = self._state
        if st.offset is not None:
            s = s.offset(st.offset)
        if st.limit is not None:
            s = s.limit(st.limit)
        return s

    def _count_select(self) -> Select[Any]:
        if self._dedupe_joined_entity_rows():
            mapper = cast("Any", inspect(self._model))
            pks = tuple(getattr(self._model, col.key) for col in mapper.primary_key)
            inner = (
                self._build_base_select(with_loader_options=False, with_order=False)
                .with_only_columns(*pks)
                .distinct()
            )
            return select(func.count()).select_from(inner.subquery())  # type: ignore[return-value,arg-type]
        inner = self._build_base_select(with_loader_options=False, with_order=False)
        return select(func.count()).select_from(inner.subquery())  # type: ignore[return-value,arg-type]

    @property
    def statement(self) -> Select[Any]:
        return self._build_select_paginated()

    def _with_state(self, new_state: QueryState) -> Self:
        return cast(
            Self,
            Query(self._session, self._model, state=new_state),
        )

    def where(self, *clauses: ColumnElement[bool]) -> Self:
        if not clauses:
            return self
        new_state = replace(self._state, wheres=(*self._state.wheres, *clauses))
        return self._with_state(new_state)

    def where_if(self, condition: object, *clauses: WhereInput) -> Self:
        """Adds where clauses only when condition is truthy.

        Each clause can be a ready expression **or** ``lambda: User.age >= x``
        when building the expression is invalid while ``condition is False``. Function call
        arguments
        are evaluated before entering ``where_if``, so ``User.age >= q.min_age``
        fails in SQLAlchemy when ``q.min_age is None``. Use ``lambda: ...`` in those cases.
        """
        if not condition:
            return self
        if not clauses:
            return self
        extra = tuple(_as_where_clause(c) for c in clauses)
        new_state = replace(self._state, wheres=(*self._state.wheres, *extra))
        return self._with_state(new_state)

    def where_not_none(
        self,
        value: TValue | None,
        builder: Callable[[TValue], ColumnElement[bool]],
    ) -> Self:
        if value is None:
            return self
        return self.where(builder(value))

    def eq_if_not_none(self, column: Any, value: Any | None) -> Self:
        return self.where_not_none(value, lambda v: cast("ColumnElement[bool]", column == v))

    def gte_if_not_none(self, column: Any, value: Any | None) -> Self:
        return self.where_not_none(value, lambda v: cast("ColumnElement[bool]", column >= v))

    def lte_if_not_none(self, column: Any, value: Any | None) -> Self:
        return self.where_not_none(value, lambda v: cast("ColumnElement[bool]", column <= v))

    def contains_if_not_none(self, column: Any, value: Any | None) -> Self:
        return self.where_not_none(
            value,
            lambda v: cast("ColumnElement[bool]", column.ilike(f"%{v!s}%")),
        )

    def join(self, *args: Any, isouter: bool = False, full: bool = False) -> Self:
        """``stmt.join(...)``: relationship, ON target, or (target, onclause), as in SQLAlchemy."""
        if not args:
            return self
        op = JoinOp.from_join(*args, isouter=isouter, full=full)
        new_state = replace(self._state, joins=(*self._state.joins, op))
        return self._with_state(new_state)

    def include(self, *keys: Any) -> Self:
        """Eager loading with ``selectinload``; convenience alias for ``selectin()``."""
        return self.selectin(*keys)

    def selectin(self, *keys: Any) -> Self:
        """``options(selectinload(...))``."""
        if not keys:
            return self
        self._assert_entity_mode_for_loader_options()
        extra = tuple(selectinload(k) for k in keys)
        new_state = replace(self._state, loader_options=(*self._state.loader_options, *extra))
        return self._with_state(new_state)

    def joined(self, *keys: Any) -> Self:
        """``options(joinedload(...))``: joined eager loading in the main query."""
        if not keys:
            return self
        self._assert_entity_mode_for_loader_options()
        extra = tuple(joinedload(k) for k in keys)
        new_state = replace(self._state, loader_options=(*self._state.loader_options, *extra))
        return self._with_state(new_state)

    def _assert_entity_mode_for_loader_options(self) -> None:
        if self._state.result_mode != "entity":
            msg = "include/selectin/joined can be used only with entity result queries"
            raise InvalidQueryStateError(msg)

    def _assert_no_loader_options_for_non_entity_result(self) -> None:
        if self._state.loader_options:
            msg = "include/selectin/joined can be used only with entity result queries"
            raise InvalidQueryStateError(msg)

    def order_by(self, *criterion: Any) -> Self:
        if not criterion:
            return self
        new_state = replace(self._state, order=(*self._state.order, *criterion))
        return self._with_state(new_state)

    def sort(
        self,
        *terms: list[Any] | Any,
    ) -> Self:
        acc: list[Any] = []
        for t in terms:
            if isinstance(t, list | tuple):
                acc.extend(cast("Iterable[Any]", t))
            else:
                acc.append(t)
        return self.order_by(*acc)

    def limit(self, n: int) -> Self:
        new_state = replace(self._state, limit=n)
        return self._with_state(new_state)

    def offset(self, n: int) -> Self:
        new_state = replace(self._state, offset=n)
        return self._with_state(new_state)

    def apply(self, filter_set: object) -> Self:
        wfn = getattr(filter_set, "_non_null_wheres", None)
        if not callable(wfn):
            return self
        extra = tuple(cast("Iterable[ColumnElement[bool]]", wfn()))
        if not extra:
            return self
        new_state = replace(self._state, wheres=(*self._state.wheres, *extra))
        return self._with_state(new_state)

    def _copy_to_result(
        self,
        *,
        projection: type[BaseModel] | None,
        explicit_cols: tuple[Any, ...] | None,
        unwrap_scalar: bool = False,
        projection_mode: ProjectionMode | None = None,
        projection_nested: ProjectionNested | None = None,
    ) -> Query[ModelT, Any]:
        st = self._state
        next_nested = projection_nested if projection_nested is not None else st.projection_nested
        is_orm_projection = projection is not None and next_nested == "orm"
        if is_orm_projection and st.explicit_cols is not None:
            msg = (
                "project(..., nested='orm') cannot be used after "
                "select(...) or select_value(...)."
            )
            raise InvalidQueryStateError(msg)
        non_entity_result = (
            (projection is not None and not is_orm_projection)
            or explicit_cols is not None
            or unwrap_scalar
        )
        if non_entity_result:
            self._assert_no_loader_options_for_non_entity_result()
        new_state = replace(
            st,
            projection=projection,
            explicit_cols=explicit_cols,
            unwrap_scalar=unwrap_scalar,
            projection_mode=projection_mode if projection_mode is not None else st.projection_mode,
            projection_nested=next_nested,
            result_mode=(
                "entity"
                if is_orm_projection
                else "projection"
                if projection is not None
                else "scalar"
                if unwrap_scalar
                else "tuple"
                if explicit_cols is not None
                else st.result_mode
            ),
        )
        return Query(self._session, self._model, state=new_state)

    def project(
        self,
        dto: type[DtoT],
        *,
        mode: ProjectionMode = "strict",
        nested: ProjectionNested = "forbid",
    ) -> Query[ModelT, DtoT]:
        return cast(
            "Query[ModelT, DtoT]",
            self._copy_to_result(
                projection=dto,
                explicit_cols=None,
                projection_mode=mode,
                projection_nested=nested,
            ),
        )

    def into(self, dto: type[DtoT]) -> Query[ModelT, DtoT]:
        cols = self._state.explicit_cols
        if cols is None:
            msg = (
                "into(DTO) can be called only after select(...). "
                "Use project(DTO) for ORM models."
            )
            raise InvalidQueryStateError(msg)
        if self._state.unwrap_scalar:
            msg = (
                "into(DTO) cannot be used after select_value(...): "
                "scalar results do not map to DTOs."
            )
            raise InvalidQueryStateError(msg)
        validate_into_columns(dto, cols)
        return cast(
            "Query[ModelT, DtoT]",
            self._copy_to_result(
                projection=dto,
                explicit_cols=cols,
                unwrap_scalar=self._state.unwrap_scalar,
            ),
        )

    @overload
    def select(  # noqa: A003
        self, __a: InstrumentedAttribute[T1] | ColumnElement[T1]
    ) -> Query[ModelT, tuple[T1]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
    ) -> Query[ModelT, tuple[T1, T2]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
    ) -> Query[ModelT, tuple[T1, T2, T3]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
        __e: InstrumentedAttribute[T5] | ColumnElement[T5],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4, T5]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
        __e: InstrumentedAttribute[T5] | ColumnElement[T5],
        __f: InstrumentedAttribute[T6] | ColumnElement[T6],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4, T5, T6]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
        __e: InstrumentedAttribute[T5] | ColumnElement[T5],
        __f: InstrumentedAttribute[T6] | ColumnElement[T6],
        __g: InstrumentedAttribute[T7] | ColumnElement[T7],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4, T5, T6, T7]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
        __e: InstrumentedAttribute[T5] | ColumnElement[T5],
        __f: InstrumentedAttribute[T6] | ColumnElement[T6],
        __g: InstrumentedAttribute[T7] | ColumnElement[T7],
        __h: InstrumentedAttribute[T8] | ColumnElement[T8],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4, T5, T6, T7, T8]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
        __e: InstrumentedAttribute[T5] | ColumnElement[T5],
        __f: InstrumentedAttribute[T6] | ColumnElement[T6],
        __g: InstrumentedAttribute[T7] | ColumnElement[T7],
        __h: InstrumentedAttribute[T8] | ColumnElement[T8],
        __i: InstrumentedAttribute[T9] | ColumnElement[T9],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4, T5, T6, T7, T8, T9]]: ...

    @overload
    def select(  # noqa: A003
        self,
        __a: InstrumentedAttribute[T1] | ColumnElement[T1],
        __b: InstrumentedAttribute[T2] | ColumnElement[T2],
        __c: InstrumentedAttribute[T3] | ColumnElement[T3],
        __d: InstrumentedAttribute[T4] | ColumnElement[T4],
        __e: InstrumentedAttribute[T5] | ColumnElement[T5],
        __f: InstrumentedAttribute[T6] | ColumnElement[T6],
        __g: InstrumentedAttribute[T7] | ColumnElement[T7],
        __h: InstrumentedAttribute[T8] | ColumnElement[T8],
        __i: InstrumentedAttribute[T9] | ColumnElement[T9],
        __j: InstrumentedAttribute[T10] | ColumnElement[T10],
    ) -> Query[ModelT, tuple[T1, T2, T3, T4, T5, T6, T7, T8, T9, T10]]: ...

    @overload
    def select(self, *entities: Any) -> Query[ModelT, tuple[Any, ...]]: ...  # noqa: A003

    def select(  # noqa: A003
        self, *entities: Any
    ) -> Query[ModelT, Any]:
        """Only the listed columns. `to_list()` returns `list[tuple[...]]` with column types."""
        return self._select_explicit(entities, unwrap_scalar=False)

    @overload
    def select_value(
        self, col: InstrumentedAttribute[TValue] | ColumnElement[TValue]
    ) -> Query[ModelT, TValue]: ...

    @overload
    def select_value(self, col: Any) -> Query[ModelT, Any]: ...

    def select_value(self, col: Any) -> Query[ModelT, Any]:
        """One column: `to_list()` returns `list[T]`, not `list[tuple[T]]`."""
        return self._select_explicit((col,), unwrap_scalar=True)

    def _select_explicit(
        self, entities: tuple[Any, ...], *, unwrap_scalar: bool
    ) -> Query[ModelT, Any]:
        self._assert_no_loader_options_for_non_entity_result()
        # Explicit columns define a new path; do not keep raw from_statement precedence.
        new_state = replace(
            self._state,
            raw=None,
            explicit_cols=entities,
            projection=None,
            unwrap_scalar=unwrap_scalar,
            result_mode="scalar" if unwrap_scalar else "tuple",
        )
        return Query(self._session, self._model, state=new_state)

    def paginate(
        self,
        page: int = 1,
        size: int = 20,
    ) -> PaginateTerminal[ResultT]:
        return PaginateTerminal(self, page=page, size=size)

    async def to_list(self) -> list[ResultT]:
        stmt = self._build_select_paginated()
        res = await self._session.execute(stmt)
        st = self._state
        if st.projection is not None:
            if st.projection_nested == "orm":
                entities = res.scalars().unique().all()
                out = [entity_to_pydantic(st.projection, entity) for entity in entities]
                return cast("list[ResultT]", out)
            source: Literal["project", "into"] = (
                "into" if st.explicit_cols is not None else "project"
            )
            out = [
                row_to_pydantic(st.projection, m, source=source) for m in res.mappings().all()
            ]
            return cast("list[ResultT]", out)
        if st.explicit_cols is not None:
            rows = res.all()
            # unwrap_scalar: select_value unwraps the scalar; select returns field tuples.
            out = [r[0] for r in rows] if st.unwrap_scalar else [tuple(r) for r in rows]
            return cast("list[ResultT]", out)
        out = list(res.scalars().unique().all())
        return cast("list[ResultT]", out)

    async def first(self) -> ResultT:
        r = await self.limit(1).to_list()
        if not r:
            raise EntityNotFound("Query.first(): result is empty")
        return r[0]

    async def first_or_none(self) -> ResultT | None:
        r = await self.limit(1).to_list()
        if not r:
            return None
        return r[0]

    async def one(self) -> ResultT:
        r = await self.limit(2).to_list()
        if len(r) == 0:
            raise EntityNotFound("Query.one(): result is empty")
        if len(r) > 1:
            raise InvalidQueryStateError("Query.one(): more than one row returned")
        return r[0]

    async def one_or_none(self) -> ResultT | None:
        r = await self.limit(2).to_list()
        if len(r) == 0:
            return None
        if len(r) > 1:
            raise InvalidQueryStateError("Query.one_or_none(): more than one row returned")
        return r[0]

    async def count(self) -> int:
        cstmt = self._count_select()
        res = await self._session.execute(cstmt)
        return int(res.scalar_one())

    async def exists(self) -> bool:
        stmt = self._build_base_select(with_loader_options=False).limit(1)
        res = await self._session.execute(stmt)
        st = self._state
        if st.projection is not None or st.explicit_cols is not None or st.raw is not None:
            return res.first() is not None
        return res.scalars().first() is not None


class PaginateTerminal(Generic[ResultT]):
    """Awaitable paginator: ``await query.paginate(page, size)`` -> ``Page[ResultT]``."""

    def __init__(self, q: Query[Any, ResultT], *, page: int, size: int) -> None:
        self._q = q
        self._page = page
        self._size = size

    def __await__(self) -> Generator[Any, None, Page[ResultT]]:
        return self._run().__await__()

    async def _run(self) -> Page[ResultT]:
        page, size = validate_page_size(self._page, self._size)
        total = await self._q.count()
        off = offset_for_page(page, size)
        inner = self._q.offset(off).limit(size)
        items = await inner.to_list()
        return Page[ResultT].from_items(  # pyright: ignore[reportUnknownMemberType]
            list(items), total=total, page=page, size=size
        )
