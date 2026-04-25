# Проекция в Pydantic: выбор колонок по полям DTO, alias, strict/loose, computed.
from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any, Literal, TypeAlias, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from sqlalchemy.orm import ColumnProperty

from queryforge.exceptions import ProjectionError

ProjectionMode: TypeAlias = Literal["strict", "loose"]
ProjectionNested: TypeAlias = Literal["forbid"]


def _unwrap_optional(tp: Any) -> Any:
    """Снимает Optional/Union c None, пока остаётся одна ветвь (кроме None)."""
    origin = get_origin(tp)
    if origin is None:
        return tp
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _unwrap_optional(args[0])
    return tp


def _is_subclass_pydantic_model(tp: Any) -> bool:
    t = _unwrap_optional(tp)
    return isinstance(t, type) and issubclass(t, BaseModel)


def _attr_name_candidates(python_name: str, f_info: FieldInfo) -> list[str]:
    out: list[str] = [python_name]
    for key in (f_info.alias, f_info.validation_alias, f_info.serialization_alias):
        if isinstance(key, str) and key and key not in out:
            out.append(key)
    return out


def _get_orm_column_descriptor(orm_model: type[Any], attr_name: str) -> Any | None:
    """Возвращает mapped-атрибут только для column property, не relationship."""
    try:
        desc = getattr(orm_model, attr_name)
    except AttributeError:
        return None
    prop = getattr(desc, "property", None)
    if prop is None:
        return None
    if isinstance(prop, ColumnProperty):
        return desc
    return None


def _map_field_to_orm_column(
    orm_model: type[Any], python_name: str, f_info: FieldInfo
) -> Any | None:
    """Mapped-атрибут ORM, соответствующий полю DTO, либо None."""
    for cand in _attr_name_candidates(python_name, f_info):
        c = _get_orm_column_descriptor(orm_model, cand)
        if c is not None:
            return c
    return None


def _is_nested_model_violation(
    dto: type[BaseModel], python_name: str, f_info: FieldInfo
) -> str | None:
    """Возвращает имя вложенного DTO, если обнаружен nested BaseModel в поле."""
    try:
        hints = get_type_hints(dto, include_extras=True)
    except (NameError, TypeError, ValueError):
        hints = {}
    resolved: Any = hints.get(python_name, f_info.annotation)
    if resolved is None:
        return None
    if _is_subclass_pydantic_model(_unwrap_optional(resolved)):
        return python_name
    return None


def _field_satisfied_without_row(f: FieldInfo) -> bool:
    """Поле не требует колонки БД: опциональное, со значением по умолчанию и т.п."""
    return not f.is_required()


def pydantic_model_columns(
    orm_model: type[Any],
    dto: type[BaseModel],
    *,
    mode: ProjectionMode = "strict",
    nested: ProjectionNested = "forbid",
) -> list[Any]:
    """Список mapped-атрибутов (колонок) в порядке полей DTO, которые маппятся в ORM.

    * ``strict`` — все требуемые поля DTO (без default) сопоставляются с колонками.
    * ``loose`` — в SELECT попадают только смаппленные на колонки поля; частичные DTO.
    * ``nested=forbid`` — вложенные BaseModel-поля не допускаются (см. join/include).
    """
    cols: list[Any] = []
    unmapped: list[str] = []
    nested_found: str | None = None
    for python_name, f_info in dto.model_fields.items():
        n = _is_nested_model_violation(dto, python_name, f_info)
        if n is not None:
            nested_found = n
            break
        c = _map_field_to_orm_column(orm_model, python_name, f_info)
        if c is not None:
            cols.append(c)
        elif not _field_satisfied_without_row(f_info):
            unmapped.append(python_name)

    if nested_found is not None:
        msg = (
            f"Поле «{nested_found}» в {dto.__name__} — вложенный DTO. "
            "Сейчас используйте плоскую схему или join/include (следующий этап)."
        )
        raise ProjectionError(msg, dto_name=dto.__name__, field_name=nested_found)

    if unmapped and mode == "strict":
        details = ", ".join(sorted({f"'{n}'" for n in unmapped}))
        msg = (
            f"project({dto.__name__}): в strict mode поля {details} "
            f"должны сопоставляться с колонками модели {getattr(orm_model, '__name__', orm_model)} "
            "или быть опциональными; с alias (Field(..., validation_alias=...)) — со столбцом."
        )
        raise ProjectionError(
            msg, dto_name=dto.__name__, unmapped_fields=tuple(sorted(set(unmapped)))
        )

    if not cols:
        msg = (
            f"project({dto.__name__}): нет полей, маппящихся на колонки "
            f"модели {getattr(orm_model, '__name__', orm_model)}. "
            "Используйте Field(alias=...) при разных имёнах "
            "или mode='loose' с частичной схемой."
        )
        raise ProjectionError(msg, dto_name=dto.__name__)

    return cols


def row_to_pydantic(dto: type[BaseModel], row: Any, *, by_alias: bool = True) -> BaseModel:
    """Строит DTO из строки; по умолчанию ``by_alias`` для ``project()`` и Field(alias=...)."""
    # RowMapping — Mapping, не dict; иначе ветка с getattr(имя поля DTO) даёт None вместо колонок
    if isinstance(row, Mapping):
        return dto.model_validate(dict(row), by_alias=by_alias)
    if hasattr(row, "_mapping"):
        m = row._mapping
        return dto.model_validate(dict(m), by_alias=by_alias)
    if isinstance(row, list | tuple):
        names = list(dto.model_fields.keys())
        d = {names[i]: row[i] for i in range(min(len(names), len(row)))}
        return dto.model_validate(d, by_alias=by_alias)
    names = list(dto.model_fields.keys())
    d = {n: getattr(row, n, None) for n in names}
    return dto.model_validate(d, by_alias=by_alias)
