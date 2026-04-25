# Конвейер Query: where, project, paginate, терминалы, statement.
# pyright: strict
from __future__ import annotations

import uuid
from collections.abc import Callable, Generator, Iterable
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, Self, TypeVar, cast, overload

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, joinedload, selectinload
from sqlalchemy.sql import ColumnElement

from queryforge.exceptions import MissingPolicyError, MissingTenantError
from queryforge.pagination import Page, offset_for_page
from queryforge.policy import PolicyAction, ReadScope
from queryforge.projection import (
    ProjectionMode,
    ProjectionNested,
    pydantic_model_columns,
    row_to_pydantic,
)
from queryforge.soft_delete import (
    SoftDeleteMode,
    has_soft_delete,
    soft_delete_clause_for_mode,
)
from queryforge.tenancy import get_tenant_id, has_tenant

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


@dataclass(frozen=True, slots=True)
class JoinOp:
    """Один вызов ``Select.join`` (args + isouter/full)."""

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
    """Неизменяемое состояние конвейера Query (where / order / limit / projection / …)."""

    wheres: tuple[ColumnElement[bool], ...] = ()
    order: tuple[Any, ...] = ()
    limit: int | None = None
    offset: int | None = None
    raw: Select[Any] | None = None
    soft_mode: SoftDeleteMode = "default"
    projection: type[BaseModel] | None = None
    explicit_cols: tuple[Any, ...] | None = None
    unwrap_scalar: bool = False
    projection_mode: ProjectionMode = "strict"
    projection_nested: ProjectionNested = "forbid"
    joins: tuple[JoinOp, ...] = ()
    loader_options: tuple[Any, ...] = ()
    tenant_mode: Literal["default", "all"] = "default"
    tenant_scope: uuid.UUID | str | int | None = None
    read_scope: ReadScope | None = None


def _as_where_clause(
    c: WhereInput,
) -> ColumnElement[bool]:
    if isinstance(c, ColumnElement):
        return cast("ColumnElement[bool]", c)
    if callable(c):
        return c()
    msg = f"where_if: ожидался ColumnElement[bool] или () -> ColumnElement, получено {type(c)!r}"
    raise TypeError(msg)


class Query(Generic[ModelT, ResultT]):
    """Конвейер поверх select(); терминалы выполняют async execute.

    Состояние неизменяемое: `where` / `order_by` / `limit` / `project` / `select` и т.д.
    возвращают новый `Query`, исходный объект не меняется. Для накопления условий
    используйте цепочку или переприсование: `q = q.where(...)`.
    """

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        *,
        state: QueryState | None = None,
        from_statement: Select[Any] | None = None,
        soft_mode: SoftDeleteMode = "default",
        projection: type[BaseModel] | None = None,
        _explicit_cols: tuple[Any, ...] | None = None,
        _unwrap_scalar: bool = False,
        _projection_mode: ProjectionMode = "strict",
        _projection_nested: ProjectionNested = "forbid",
        read_scope: ReadScope | None = None,
    ) -> None:
        self._session = session
        self._model: type[ModelT] = model
        if state is not None:
            self._state = state
        else:
            self._state = QueryState(
                raw=from_statement,
                soft_mode=soft_mode,
                projection=projection,
                explicit_cols=_explicit_cols,
                unwrap_scalar=_unwrap_scalar,
                projection_mode=_projection_mode,
                projection_nested=_projection_nested,
                tenant_mode="all" if from_statement is not None else "default",
                read_scope=read_scope,
            )

    def _map_soft_mode(self) -> SoftDeleteMode:
        st = self._state.soft_mode
        if st == "default":
            return "default"
        if st == "with_all":
            return "with_all"
        return "only_deleted"

    def _soft_wheres(self) -> list[ColumnElement[bool]]:
        if self._state.raw is not None or not has_soft_delete(self._model):
            return []
        return list(soft_delete_clause_for_mode(self._model, self._map_soft_mode()))

    def _effective_tenant_id_for_filter(self) -> uuid.UUID | str | int:
        st = self._state
        if st.tenant_scope is not None:
            return st.tenant_scope
        tid = get_tenant_id()
        if tid is None:
            msg = "Для tenant-scoped модели укажите TenantContext или query.for_tenant(...)"
            raise MissingTenantError(msg)
        return tid

    def _tenant_wheres(self) -> list[ColumnElement[bool]]:
        if self._state.raw is not None or not has_tenant(self._model):
            return []
        if self._state.tenant_mode == "all":
            return []
        eff = self._effective_tenant_id_for_filter()
        col = self._model.tenant_id
        return [col == eff]

    def _all_wheres(self) -> list[ColumnElement[bool]]:
        return [*self._state.wheres, *self._soft_wheres(), *self._tenant_wheres()]

    def _build_base_select(self, *, with_loader_options: bool = True) -> Select[Any]:
        st = self._state
        if st.raw is not None:
            s = st.raw
        elif st.explicit_cols is not None:
            s = select(*st.explicit_cols)  # type: ignore[arg-type]
        elif st.projection is not None:
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
        inner = self._build_base_select(with_loader_options=False)
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
        """Добавляет where только если condition истинно.

        Каждое из clauses может быть готовым выражением **или** ``lambda: User.age >= x``,
        если при ``condition is False`` выражение строить нельзя: аргументы вызова ``where_if``
        вычисляются в Python до входа в метод, поэтому ``User.age >= q.min_age`` при
        ``q.min_age is None`` падает в SQLAlchemy. Используйте ``lambda: ...`` в таких случаях.
        """
        if not condition:
            return self
        if not clauses:
            return self
        extra = tuple(_as_where_clause(c) for c in clauses)
        new_state = replace(self._state, wheres=(*self._state.wheres, *extra))
        return self._with_state(new_state)

    def join(self, *args: Any, isouter: bool = False, full: bool = False) -> Self:
        """``stmt.join(...)`` — связь, цель ON или (target, onclause) как в SQLAlchemy."""
        if not args:
            return self
        op = JoinOp.from_join(*args, isouter=isouter, full=full)
        new_state = replace(self._state, joins=(*self._state.joins, op))
        return self._with_state(new_state)

    def include(self, *keys: Any) -> Self:
        """Eager: ``selectinload`` — то же, что ``selectin()`` (удобный алиас)."""
        return self.selectin(*keys)

    def selectin(self, *keys: Any) -> Self:
        """``options(selectinload(...))``."""
        if not keys:
            return self
        extra = tuple(selectinload(k) for k in keys)
        new_state = replace(self._state, loader_options=(*self._state.loader_options, *extra))
        return self._with_state(new_state)

    def joined(self, *keys: Any) -> Self:
        """``options(joinedload(...))`` — одним JOIN-ом в основном запросе."""
        if not keys:
            return self
        extra = tuple(joinedload(k) for k in keys)
        new_state = replace(self._state, loader_options=(*self._state.loader_options, *extra))
        return self._with_state(new_state)

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

    def for_tenant(self, tenant_id: uuid.UUID | str | int) -> Self:
        """Ограничить выборку одним tenant (без глобального ``TenantContext``)."""
        new_state = replace(
            self._state,
            tenant_scope=tenant_id,
            tenant_mode="default",
        )
        return self._with_state(new_state)

    def with_all_tenants(self) -> Self:
        """Все tenant; использовать только при явной необходимости (например админ-задача)."""
        new_state = replace(self._state, tenant_mode="all")
        return self._with_state(new_state)

    def visible_for(self, user: Any) -> Self:
        """Фильтр по политике репозитория: ``read_scope`` в ``Repository(...)``."""
        fn = self._state.read_scope
        if fn is None:
            msg = "visible_for: не задан read_scope в Repository(..., read_scope=...)"
            raise MissingPolicyError(msg)
        return self.where(fn(self._model, user))

    def allowed_by(self, action: PolicyAction, user: Any) -> Self:
        """Фильтр по действию, например ``allowed_by(UserPolicy.read, current_user)``."""
        return self.where(action(user))

    def with_deleted(self) -> Self:
        new_state = replace(self._state, soft_mode="with_all")
        return self._with_state(new_state)

    def only_deleted(self) -> Self:
        new_state = replace(self._state, soft_mode="only_deleted")
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
        new_state = replace(
            st,
            projection=projection,
            explicit_cols=explicit_cols,
            unwrap_scalar=unwrap_scalar,
            projection_mode=projection_mode if projection_mode is not None else st.projection_mode,
            projection_nested=projection_nested
            if projection_nested is not None
            else st.projection_nested,
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
        """Только перечисленные колонки. `to_list()` — `list[tuple[...]]` с типами колонок."""
        return self._select_explicit(entities, unwrap_scalar=False)

    @overload
    def select_value(
        self, col: InstrumentedAttribute[TValue] | ColumnElement[TValue]
    ) -> Query[ModelT, TValue]: ...

    @overload
    def select_value(self, col: Any) -> Query[ModelT, Any]: ...

    def select_value(self, col: Any) -> Query[ModelT, Any]:
        """Одна колонка: `to_list()` возвращает `list[T]`, а не `list[tuple[T]]`."""
        return self._select_explicit((col,), unwrap_scalar=True)

    def _select_explicit(
        self, entities: tuple[Any, ...], *, unwrap_scalar: bool
    ) -> Query[ModelT, Any]:
        # Явные колонки — новый путь; не тянем сырой from_statement, иначе приоритет у raw
        new_state = replace(
            self._state,
            raw=None,
            explicit_cols=entities,
            projection=None,
            unwrap_scalar=unwrap_scalar,
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
            out = [row_to_pydantic(st.projection, m) for m in res.mappings().all()]
            return cast("list[ResultT]", out)
        if st.explicit_cols is not None:
            rows = res.all()
            # unwrap_scalar: select_value снимает скаляр; select — кортежи полей
            out = [r[0] for r in rows] if st.unwrap_scalar else [tuple(r) for r in rows]
            return cast("list[ResultT]", out)
        out = list(res.scalars().unique().all())
        return cast("list[ResultT]", out)

    async def first(self) -> ResultT:
        r = await self.limit(1).to_list()
        if not r:
            raise RuntimeError("Query.first(): пусто")
        return r[0]

    async def first_or_none(self) -> ResultT | None:
        r = await self.limit(1).to_list()
        if not r:
            return None
        return r[0]

    async def one(self) -> ResultT:
        r = await self.limit(2).to_list()
        if len(r) == 0:
            raise RuntimeError("Query.one(): пусто")
        if len(r) > 1:
            raise RuntimeError("Query.one(): получено > 1 строки")
        return r[0]

    async def one_or_none(self) -> ResultT | None:
        r = await self.limit(2).to_list()
        if len(r) == 0:
            return None
        if len(r) > 1:
            raise RuntimeError("Query.one_or_none(): получено > 1 строки")
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
    """Ожидаемый пагинатор: ``await query.paginate(page, size)`` -> ``Page[ResultT]``."""

    def __init__(self, q: Query[Any, ResultT], *, page: int, size: int) -> None:
        self._q = q
        self._page = page
        self._size = size

    def __await__(self) -> Generator[Any, None, Page[ResultT]]:
        return self._run().__await__()

    async def _run(self) -> Page[ResultT]:
        total = await self._q.count()
        off = offset_for_page(self._page, self._size)
        inner = self._q.offset(off).limit(self._size)
        items = await inner.to_list()
        return Page[ResultT].from_items(  # pyright: ignore[reportUnknownMemberType]
            list(items), total=total, page=self._page, size=self._size
        )
