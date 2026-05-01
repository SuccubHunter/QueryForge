# Pydantic projection: select columns by DTO fields, alias, strict/loose, computed.
from __future__ import annotations

import types
from collections.abc import Mapping
from typing import Any, Literal, TypeAlias, Union, get_args, get_origin, get_type_hints

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo
from sqlalchemy.orm import ColumnProperty

from queryforge.exceptions import ProjectionError

ProjectionMode: TypeAlias = Literal["strict", "loose"]
ProjectionNested: TypeAlias = Literal["forbid", "orm"]


def _unwrap_optional(tp: Any) -> Any:
    """Unwraps Optional/Union with None while one non-None branch remains."""
    origin = get_origin(tp)
    if origin is None:
        return tp
    if origin is Union or origin is types.UnionType:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return _unwrap_optional(args[0])
    return tp


def _contains_pydantic_model(tp: Any) -> bool:
    t = _unwrap_optional(tp)
    if isinstance(t, type) and issubclass(t, BaseModel):
        return True
    origin = get_origin(t)
    if origin is None:
        return False
    return any(_contains_pydantic_model(arg) for arg in get_args(t))


def _attr_name_candidates(python_name: str, f_info: FieldInfo) -> list[str]:
    out: list[str] = [python_name]
    for key in (f_info.alias, f_info.validation_alias, f_info.serialization_alias):
        if isinstance(key, str) and key and key not in out:
            out.append(key)
    return out


def _add_string_candidate(out: list[str], value: Any) -> None:
    if not isinstance(value, str) or not value:
        return
    if value not in out:
        out.append(value)


def _column_name_candidates(column: Any) -> tuple[str, ...]:
    """Names under which the selected column may appear in RowMapping."""
    out: list[str] = []
    for attr in ("key", "name", "_label", "description"):
        _add_string_candidate(out, getattr(column, attr, None))

    prop = getattr(column, "property", None)
    _add_string_candidate(out, getattr(prop, "key", None))

    # Label / SQL expression often wraps the original ORM column in ``.element``.
    element = getattr(column, "element", None)
    if element is not None and element is not column:
        for name in _column_name_candidates(element):
            _add_string_candidate(out, name)
    return tuple(out)


def _get_orm_column_descriptor(orm_model: type[Any], attr_name: str) -> Any | None:
    """Returns a mapped attribute only for column properties, not relationships."""
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
    """ORM mapped attribute matching the DTO field, or None."""
    for cand in _attr_name_candidates(python_name, f_info):
        c = _get_orm_column_descriptor(orm_model, cand)
        if c is not None:
            return c
    return None


def _is_nested_model_violation(
    dto: type[BaseModel], python_name: str, f_info: FieldInfo
) -> str | None:
    """Returns the nested DTO field name when a nested BaseModel is detected."""
    try:
        hints = get_type_hints(dto, include_extras=True)
    except (NameError, TypeError, ValueError):
        hints = {}
    resolved: Any = hints.get(python_name, f_info.annotation)
    if resolved is None:
        return None
    if _contains_pydantic_model(resolved):
        return python_name
    return None


def _field_satisfied_without_row(f: FieldInfo) -> bool:
    """The field does not require a DB column: optional, has a default, etc."""
    return not f.is_required() or type(None) in get_args(f.annotation)


def _fill_optional_nones(dto: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    for name, f_info in dto.model_fields.items():
        keys = _attr_name_candidates(name, f_info)
        if any(key in out for key in keys):
            continue
        if type(None) in get_args(f_info.annotation):
            out[name] = None
    return out


def pydantic_model_columns(
    orm_model: type[Any],
    dto: type[BaseModel],
    *,
    mode: ProjectionMode = "strict",
    nested: ProjectionNested = "forbid",
) -> list[Any]:
    """Mapped attributes (columns) ordered by DTO fields that map to ORM columns.

    * ``strict``: all required DTO fields without defaults must map to columns.
    * ``loose``: SELECT includes only fields mapped to columns; partial DTOs.
    * ``nested=forbid``: nested BaseModel fields are rejected (see join/include).
    * ``nested=orm``: does not build SQL projection; DTO is assembled from ORM entities.
    """
    if nested == "orm":
        return []

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
            f"Field '{nested_found}' in {dto.__name__} is a nested DTO. "
            "Nested DTOs are forbidden by default: use a flat schema or "
            "project(..., nested='orm') together with eager loading."
        )
        raise ProjectionError(msg, dto_name=dto.__name__, field_name=nested_found)

    if unmapped and mode == "strict":
        details = ", ".join(sorted({f"'{n}'" for n in unmapped}))
        msg = (
            f"project({dto.__name__}): in strict mode, fields {details} "
            f"must map to columns of model {getattr(orm_model, '__name__', orm_model)} "
            "or be optional; with alias (Field(..., validation_alias=...)) "
            "they must map to a column."
        )
        raise ProjectionError(
            msg, dto_name=dto.__name__, unmapped_fields=tuple(sorted(set(unmapped)))
        )

    if not cols:
        msg = (
            f"project({dto.__name__}): has no fields mapping to columns of "
            f"model {getattr(orm_model, '__name__', orm_model)}. "
            "Use Field(alias=...) when names differ "
            "or mode='loose' with a partial schema."
        )
        raise ProjectionError(msg, dto_name=dto.__name__)

    return cols


def validate_into_columns(dto: type[BaseModel], selected_columns: tuple[Any, ...]) -> None:
    """Checks that ``select(...).into(DTO)`` covers required DTO fields."""
    available: set[str] = set()
    for column in selected_columns:
        available.update(_column_name_candidates(column))

    unmapped: list[str] = []
    for python_name, f_info in dto.model_fields.items():
        n = _is_nested_model_violation(dto, python_name, f_info)
        if n is not None:
            msg = (
                f"Field '{n}' in {dto.__name__} is a nested DTO. "
                "into(DTO) supports only a flat selected-column shape."
            )
            raise ProjectionError(msg, dto_name=dto.__name__, field_name=n)

        candidates = _attr_name_candidates(python_name, f_info)
        if any(name in available for name in candidates):
            continue
        if not _field_satisfied_without_row(f_info):
            unmapped.append(python_name)

    if unmapped:
        details = ", ".join(sorted({f"'{n}'" for n in unmapped}))
        msg = (
            f"into({dto.__name__}): selected columns do not cover required fields "
            f"{details}. Add columns to select(...) or define alias/default/optional fields."
        )
        raise ProjectionError(
            msg, dto_name=dto.__name__, unmapped_fields=tuple(sorted(set(unmapped)))
        )


def row_to_pydantic(
    dto: type[BaseModel],
    row: Any,
    *,
    by_alias: bool = True,
    source: Literal["project", "into"] = "project",
) -> BaseModel:
    """Builds a DTO from a row.

    ``by_alias`` defaults to support ``project()`` and Field(alias=...).
    """
    try:
        # RowMapping is Mapping, not dict; otherwise getattr(DTO field name)
        # returns None instead of columns.
        if isinstance(row, Mapping):
            return dto.model_validate(_fill_optional_nones(dto, dict(row)), by_alias=by_alias)
        if hasattr(row, "_mapping"):
            m = row._mapping
            return dto.model_validate(_fill_optional_nones(dto, dict(m)), by_alias=by_alias)
        if isinstance(row, list | tuple):
            names = list(dto.model_fields.keys())
            d = {names[i]: row[i] for i in range(min(len(names), len(row)))}
            return dto.model_validate(_fill_optional_nones(dto, d), by_alias=by_alias)
        names = list(dto.model_fields.keys())
        d = {n: getattr(row, n, None) for n in names}
        return dto.model_validate(_fill_optional_nones(dto, d), by_alias=by_alias)
    except ValidationError as e:
        if source == "into":
            msg = (
                f"into({dto.__name__}): the current result shape does not match the DTO. "
                "Check column names, label(...), aliases and field types."
            )
            raise ProjectionError(msg, dto_name=dto.__name__) from e
        raise


def entity_to_pydantic(dto: type[BaseModel], entity: Any) -> BaseModel:
    """Builds a DTO from an ORM entity through Pydantic from_attributes=True."""
    try:
        return dto.model_validate(entity, from_attributes=True)
    except ValidationError as e:
        msg = (
            f"project({dto.__name__}, nested='orm'): ORM entity does not match the DTO. "
            "Check eager loading, from_attributes-compatible fields and nested schemas."
        )
        raise ProjectionError(msg, dto_name=dto.__name__) from e
