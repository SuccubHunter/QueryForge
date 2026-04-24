# Проекция в Pydantic: выбор колонок по полям DTO.
from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Имена полей Pydantic должны соответствовать mapped-атрибутам SQLAlchemy-модели


def pydantic_model_columns(orm_model: type[Any], dto: type[BaseModel]) -> list[Any]:
    """Список колонок/дескрипторов в порядке полей DTO."""
    fields = getattr(dto, "model_fields", None)
    if not fields:
        return []
    out: list[Any] = []
    for name in fields:
        if not hasattr(orm_model, name):
            continue
        out.append(getattr(orm_model, name))
    return out


def row_to_pydantic(dto: type[BaseModel], row: Any) -> BaseModel:
    if isinstance(row, dict):
        return dto.model_validate(row)
    if hasattr(row, "_mapping"):
        m = row._mapping
        return dto.model_validate(dict(m))
    if isinstance(row, list | tuple):
        names = list(dto.model_fields.keys())
        d = {names[i]: row[i] for i in range(min(len(names), len(row)))}
        return dto.model_validate(d)
    names = list(dto.model_fields.keys())
    d = {n: getattr(row, n, None) for n in names}
    return dto.model_validate(d)
