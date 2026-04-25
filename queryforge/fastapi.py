# FastAPI: Depends(Repository), QueryParams, пагинация/сортировка, OpenAPI.
from __future__ import annotations

from typing import (
    Annotated,
    Any,
    ClassVar,
    Self,
    TypeVar,
    get_args,
    get_origin,
)

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Depends, Query
from queryforge.filters import FilterSet
from queryforge.pagination import Page
from queryforge.policy import ReadScope
from queryforge.repository import Repository
from queryforge.sorting import SortSetBase

M = TypeVar("M")
F = TypeVar("F", bound=FilterSet[Any])

# Глобальная зависимость: установите через set_session_dep(get_async_session).
_default_session_dep: Any = None


def set_session_dep(session_dep: Any) -> None:
    """Сохраняет Depends-фабрику сессии для repo() без session_dep=."""
    global _default_session_dep
    _default_session_dep = session_dep


def get_session_dep() -> Any:
    return _default_session_dep


def repo(
    model: type[M],
    *,
    session_dep: Any | None = None,
    read_scope: ReadScope | None = None,
) -> Any:
    """Session -> Repository. Пример: ``Depends(repo(User, session_dep=get_session))``.

    Для ``query().visible_for(current_user)`` укажите ``read_scope`` (см. ``queryforge.policy``).
    В обработчике: ``user = Depends(get_current_user)``, затем
    ``await repo.query().visible_for(user).to_list()``.
    """
    dep = session_dep or _default_session_dep
    if dep is None:
        msg = "Укажите session_dep=... в repo() или set_session_dep(Depends get_session)."
        raise RuntimeError(msg)

    async def _inner(
        session: AsyncSession = Depends(dep),  # noqa: B008
    ) -> Repository[M]:
        return Repository(session, model, read_scope=read_scope)

    return _inner


def filterset_query(model_type: type[F]) -> Any:
    """Аннотация для query-параметров ``FilterSet`` (требуется FastAPI ≥ 0.115).

    Поля схемы попадают в OpenAPI по одному; валидация — как у Pydantic ``BaseModel``.
    """
    return Annotated[model_type, Query()]


class PaginationParams(BaseModel):
    """Параметры пагинации из query string (``page``, ``size``)."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    page: int = Field(default=1, ge=1, description="Номер страницы (с 1)")
    size: int = Field(default=20, ge=1, le=500, description="Размер страницы")


def pagination_params() -> Any:
    """``Annotated`` для внедрения :class:`PaginationParams` из query (OpenAPI)."""
    return Annotated[PaginationParams, Query()]


class SortParams(BaseModel):
    """Один query-параметр ``sort``; разбор в выражения order_by через ``SortSet``."""

    model_config = ConfigDict(extra="forbid", validate_default=True, str_strip_whitespace=True)

    sort: str | None = Field(
        default=None,
        description=(
            "Поля через запятую; префикс «-» у поля — по убыванию (пример: -created_at,email)"
        ),
    )

    def order_terms(self, sort_set: type[SortSetBase[Any]]) -> list[Any]:
        if self.sort is None or not str(self.sort).strip():
            return sort_set.from_param("")
        return sort_set.from_param(self.sort)


def sort_params() -> Any:
    """``Annotated`` для :class:`SortParams` из query (OpenAPI)."""
    return Annotated[SortParams, Query()]


def _is_sort_set_type(x: type[Any]) -> bool:
    try:
        return bool(issubclass(x, SortSetBase) and x is not SortSetBase)
    except TypeError:
        return False


def _build_query_params_class(
    filter_cls: type[FilterSet[Any]],
    sort_set_cls: type[SortSetBase[Any]],
) -> type[BaseModel]:
    if not (isinstance(filter_cls, type) and issubclass(filter_cls, FilterSet)):
        msg = f"QueryParams: ожидался подкласс FilterSet, получено {filter_cls!r}"
        raise TypeError(msg)
    if not _is_sort_set_type(sort_set_cls):
        msg = f"QueryParams: ожидался подкласс SortSet/SortSetBase, получено {sort_set_cls!r}"
        raise TypeError(msg)
    s_ref: type[SortSetBase[Any]] = sort_set_cls
    f_cfg: Any = getattr(filter_cls, "model_config", None)
    merge_cfg: dict[str, Any] = {}
    if isinstance(f_cfg, dict):
        merge_cfg = {
            **f_cfg,
            "extra": "forbid",
            "validate_default": True,
            "str_strip_whitespace": True,
        }
    else:
        merge_cfg = ConfigDict(extra="forbid", validate_default=True, str_strip_whitespace=True)  # type: ignore[assignment]

    # Динамический подкласс: фильтры + page/size/sort + валидация сортировки
    class _Merged(filter_cls):  # type: ignore[valid-type, misc]
        __pydantic_sort_set__: ClassVar[type[SortSetBase[Any]]] = s_ref
        __pydantic_filter_type__: ClassVar[type[FilterSet[Any]]] = filter_cls

        model_config = ConfigDict(**merge_cfg) if isinstance(merge_cfg, dict) else merge_cfg

        page: int = Field(default=1, ge=1, description="Номер страницы (с 1)")
        size: int = Field(default=20, ge=1, le=500, description="Размер страницы")
        sort: str | None = Field(
            default=None,
            description=(
                "Поля через запятую; префикс «-» — по убыванию (например -created_at,email)"
            ),
        )

        @model_validator(mode="after")
        def _check_sort_against_set(self) -> Self:
            if self.sort is None or not str(self.sort).strip():
                try:
                    s_ref.from_param("")
                except ValueError as e:
                    raise ValueError(str(e)) from e
                return self
            try:
                s_ref.from_param(self.sort)
            except ValueError as e:
                raise ValueError(str(e)) from e
            return self

        def sort_terms(self) -> list[Any]:
            if self.sort is None or not str(self.sort).strip():
                return s_ref.from_param("")
            return s_ref.from_param(self.sort)

    out_name = f"{filter_cls.__name__}QueryParams"
    _Merged.__name__ = out_name
    _Merged.__qualname__ = out_name
    return _Merged


class QueryParams:
    """Фабрика схемы query: ``class U(QueryParams[UserFilters, UserSorts]): ...``.

    ``QueryParams[FilterSet, SortSet]`` возвращает Pydantic-модель: поля фильтра, ``page``,
    ``size``, ``sort`` и метод :meth:`sort_terms`.
    """

    @classmethod
    def __class_getitem__(cls, item: Any) -> type[BaseModel]:
        origin = get_origin(item)
        args = get_args(item) if origin is not None else None
        if args is not None and len(args) == 2:
            f_t, s_t = args[0], args[1]
        else:
            if not isinstance(item, tuple) or len(item) != 2:
                raise TypeError("QueryParams[FilterSet, SortSet] — ровно два типа-аргумента")
            f_t, s_t = item[0], item[1]
        if not (isinstance(f_t, type) and isinstance(s_t, type)):
            raise TypeError("QueryParams: аргументы должны быть классами")
        return _build_query_params_class(
            f_t,  # type: ignore[arg-type]
            s_t,  # type: ignore[arg-type]
        )


def query_params_annotated(
    filter_cls: type[FilterSet[Any]],
    sort_set_cls: type[SortSetBase[Any]],
) -> Any:
    """``Annotated[…, Query()]`` для единой схемы query (фильтр + page + size + sort).

    При ``from __future__ import annotations`` псевдоним (результат этой функции) задайте
    **на уровне модуля**, иначе у вложенного обработчика FastAPI/Pydantic не хватит
    разрешения имён для OpenAPI.
    """
    m = _build_query_params_class(filter_cls, sort_set_cls)
    return Annotated[m, Query()]


def page_response_type(item_type: type[BaseModel]) -> type[Page[Any]]:
    """Тип ответа для ``response_model`` (OpenAPI / typing), например ``Page[UserRead]``."""
    return Page[item_type]  # type: ignore[return-value, valid-type]


__all__ = [
    "QueryParams",
    "PaginationParams",
    "SortParams",
    "filterset_query",
    "get_session_dep",
    "page_response_type",
    "pagination_params",
    "query_params_annotated",
    "repo",
    "set_session_dep",
    "sort_params",
]
