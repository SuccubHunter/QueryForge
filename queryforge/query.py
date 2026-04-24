# Конвейер Query: where, project, paginate, терминалы, statement.
# pyright: strict
from __future__ import annotations

from collections.abc import Callable, Generator, Iterable
from typing import Any, Generic, Self, TypeVar, cast, overload

from pydantic import BaseModel
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from queryforge.pagination import Page, offset_for_page
from queryforge.projection import pydantic_model_columns, row_to_pydantic
from queryforge.soft_delete import (
    SoftDeleteMode,
    has_soft_delete,
    soft_delete_clause_for_mode,
)

ModelT = TypeVar("ModelT", bound=Any)
ResultT = TypeVar("ResultT", bound=Any)
DtoT = TypeVar("DtoT", bound=BaseModel)

WhereInput = ColumnElement[bool] | Callable[[], ColumnElement[bool]]


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
    """Конвейер поверх select(); терминалы выполняют async execute."""

    def __init__(
        self,
        session: AsyncSession,
        model: type[ModelT],
        *,
        from_statement: Select[Any] | None = None,
        soft_mode: SoftDeleteMode = "default",
        projection: type[BaseModel] | None = None,
        _explicit_cols: list[Any] | None = None,
    ) -> None:
        self._session = session
        self._model: type[ModelT] = model
        self._wheres: list[ColumnElement[bool]] = []
        self._order: list[Any] = []
        self._limit: int | None = None
        self._offset: int | None = None
        self._raw: Select[Any] | None = from_statement
        self._soft_mode: SoftDeleteMode = soft_mode
        self._projection: type[BaseModel] | None = projection
        self._explicit_cols: list[Any] | None = _explicit_cols

    def _map_soft_mode(self) -> SoftDeleteMode:
        if self._soft_mode == "default":
            return "default"
        if self._soft_mode == "with_all":
            return "with_all"
        return "only_deleted"

    def _soft_wheres(self) -> list[ColumnElement[bool]]:
        if self._raw is not None or not has_soft_delete(self._model):
            return []
        return list(soft_delete_clause_for_mode(self._model, self._map_soft_mode()))

    def _all_wheres(self) -> list[ColumnElement[bool]]:
        return [*self._wheres, *self._soft_wheres()]

    def _build_base_select(self) -> Select[Any]:
        if self._raw is not None:
            s = self._raw
        elif self._explicit_cols is not None:
            s = select(*self._explicit_cols)  # type: ignore[arg-type]
        elif self._projection is not None:
            cols = pydantic_model_columns(self._model, self._projection)
            if not cols:
                msg = (
                    f"project({self._projection.__name__}): нет совпадений полей DTO с колонками "
                    f"модели {getattr(self._model, '__name__', self._model)}. "
                    "Имена полей Pydantic должны соответствовать mapped-атрибутам."
                )
                raise ValueError(msg)
            s = select(*cols)  # type: ignore[call-overload,arg-type]
        else:
            s = select(self._model)  # type: ignore[call-overload]
        for w in self._all_wheres():
            s = s.where(w)
        for o in self._order:
            s = s.order_by(o)  # type: ignore[call-overload]
        return s

    def _build_select_paginated(self) -> Select[Any]:
        s = self._build_base_select()
        if self._offset is not None:
            s = s.offset(self._offset)
        if self._limit is not None:
            s = s.limit(self._limit)
        return s

    def _count_select(self) -> Select[Any]:
        inner = self._build_base_select()
        return select(func.count()).select_from(inner.subquery())  # type: ignore[return-value,arg-type]

    @property
    def statement(self) -> Select[Any]:
        return self._build_select_paginated()

    def where(self, *clauses: ColumnElement[bool]) -> Self:
        for c in clauses:
            self._wheres.append(c)
        return self

    def where_if(self, condition: object, *clauses: WhereInput) -> Self:
        """Добавляет where только если condition истинно.

        Каждое из clauses может быть готовым выражением **или** ``lambda: User.age >= x``,
        если при ``condition is False`` выражение строить нельзя: аргументы вызова ``where_if``
        вычисляются в Python до входа в метод, поэтому ``User.age >= q.min_age`` при
        ``q.min_age is None`` падает в SQLAlchemy. Используйте ``lambda: ...`` в таких случаях.
        """
        if not condition:
            return self
        for c in clauses:
            self._wheres.append(_as_where_clause(c))
        return self

    def order_by(self, *criterion: Any) -> Self:
        self._order.extend(criterion)
        return self

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
        self._limit = n
        return self

    def offset(self, n: int) -> Self:
        self._offset = n
        return self

    def apply(self, filter_set: object) -> Self:
        wfn = getattr(filter_set, "_non_null_wheres", None)
        if callable(wfn):
            for w in cast("Iterable[ColumnElement[bool]]", wfn()):
                self._wheres.append(w)
        return self

    def with_deleted(self) -> Self:
        self._soft_mode = "with_all"
        return self

    def only_deleted(self) -> Self:
        self._soft_mode = "only_deleted"
        return self

    def _copy_to_result(
        self,
        *,
        projection: type[BaseModel] | None,
        explicit_cols: list[Any] | None,
    ) -> Query[ModelT, Any]:
        q: Query[ModelT, Any] = Query(
            self._session,
            self._model,
            from_statement=self._raw,
            soft_mode=self._soft_mode,
            projection=projection,
            _explicit_cols=explicit_cols,
        )
        q._wheres = list(self._wheres)
        q._order = list(self._order)
        q._limit = self._limit
        q._offset = self._offset
        return q

    def project(self, dto: type[DtoT]) -> Query[ModelT, DtoT]:
        return cast(
            "Query[ModelT, DtoT]",
            self._copy_to_result(projection=dto, explicit_cols=None),
        )

    def into(self, dto: type[DtoT]) -> Query[ModelT, DtoT]:
        cols = list(self._explicit_cols) if self._explicit_cols is not None else None
        return cast(
            "Query[ModelT, DtoT]",
            self._copy_to_result(projection=dto, explicit_cols=cols),
        )

    @overload
    def select(self, __a: Any) -> Query[ModelT, tuple[Any]]: ...  # noqa: A003

    @overload
    def select(self, __a: Any, __b: Any) -> Query[ModelT, tuple[Any, Any]]: ...

    @overload
    def select(self, __a: Any, __b: Any, __c: Any) -> Query[ModelT, tuple[Any, Any, Any]]: ...

    @overload
    def select(
        self, __a: Any, __b: Any, __c: Any, __d: Any
    ) -> Query[ModelT, tuple[Any, Any, Any, Any]]: ...

    @overload
    def select(
        self, __a: Any, __b: Any, __c: Any, __d: Any, __e: Any
    ) -> Query[ModelT, tuple[Any, Any, Any, Any, Any]]: ...

    @overload
    def select(self, *entities: Any) -> Query[ModelT, Any]: ...

    def select(  # noqa: A003
        self, *entities: Any
    ) -> Query[ModelT, Any]:
        q: Query[ModelT, Any] = Query(
            self._session,
            self._model,
            soft_mode=self._soft_mode,
            from_statement=None,
        )
        q._wheres = list(self._wheres)
        q._order = list(self._order)
        # Явные колонки — новый путь; не тянем сырой from_statement, иначе приоритет у _raw
        q._raw = None
        q._explicit_cols = list(entities)
        q._projection = None
        return q

    def paginate(
        self,
        page: int = 1,
        size: int = 20,
    ) -> PaginateTerminal[ResultT]:
        return PaginateTerminal(self, page=page, size=size)

    async def to_list(self) -> list[ResultT]:
        stmt = self._build_select_paginated()
        res = await self._session.execute(stmt)
        if self._projection is not None:
            out = [row_to_pydantic(self._projection, m) for m in res.mappings().all()]
            return cast("list[ResultT]", out)
        if self._explicit_cols is not None:
            out = [tuple(r) for r in res.all()]
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
        stmt = self._build_base_select().limit(1)
        res = await self._session.execute(stmt)
        if self._projection is not None or self._explicit_cols is not None or self._raw is not None:
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
