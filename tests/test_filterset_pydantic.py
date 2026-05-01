# FilterSet: Pydantic, validation, to_wheres, assert_type.
from __future__ import annotations

from typing import assert_type

import pytest
from pydantic import ValidationError
from queryforge import FilterSet, contains, eq, gte
from sqlalchemy.sql import ColumnElement

from tests.models import User, UserStatus


class UserFilters(FilterSet[User]):
    status: UserStatus | None = eq(User.status)
    min_age: int | None = gte(User.age)
    email: str | None = contains(User.email)


def test_user_filters_rejects_non_int_min_age() -> None:
    with pytest.raises(ValidationError, match="min_age"):
        UserFilters(min_age="abc")


def test_to_wheres_typing() -> None:
    w = UserFilters(min_age=18).to_wheres()
    assert_type(w, list[ColumnElement[bool]])
    assert all(isinstance(x, ColumnElement) for x in w)


def test_model_json_schema_has_typed_fields() -> None:
    s = UserFilters.model_json_schema()
    props = s.get("properties", {})
    assert "min_age" in props
    assert "status" in props
    # int | null in JSON schema (number + null)
    assert props["min_age"].get("anyOf") is not None or "integer" in str(props.get("min_age", {}))
