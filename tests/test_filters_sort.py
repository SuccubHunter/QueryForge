# FilterSet, SortSet.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import (
    FilterSet,
    InvalidSortError,
    Repository,
    SortSet,
    asc,
    contains,
    desc,
    eq,
    gte,
)
from sqlalchemy import select
from sqlalchemy.dialects import sqlite

from tests.models import User, UserStatus


class UserFilters(FilterSet[User]):
    status = eq(User.status)
    min_age = gte(User.age)
    email = contains(User.email)


class UserSorts(SortSet[User]):
    email = asc(User.email)
    created_at = desc(User.created_at)


async def _seed_one(session) -> None:
    u = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        age=30,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()


@pytest.mark.asyncio
async def test_filter_set_apply(session) -> None:
    await _seed_one(session)
    repo = Repository(session, User)
    f = UserFilters(
        status=UserStatus.ACTIVE,
        min_age=20,
        email="example",
    )
    n = await repo.query().apply(f).count()
    assert n == 1


@pytest.mark.asyncio
async def test_sort_from_param(session) -> None:
    await _seed_one(session)
    repo = Repository(session, User)
    u = await repo.query().sort(UserSorts.from_param("-created_at")).first()
    assert u is not None
    assert u.email == "admin@example.com"


def test_sort_from_param_multi_and_pk() -> None:
    class S(SortSet[User]):
        email = asc(User.email)
        created_at = desc(User.created_at)

    terms = S.from_param("-created_at,email")
    assert len(terms) == 3


def test_sort_from_param_default_sort() -> None:
    class S(SortSet[User]):
        __default_sort__ = "email"
        email = asc(User.email)
        created_at = desc(User.created_at)

    terms = S.from_param("")
    assert len(terms) == 2


def test_sort_alias_resolves() -> None:
    class S(SortSet[User]):
        created_at = desc(User.created_at, alias="cr")
        email = asc(User.email)

    assert len(S.from_param("cr")) == 2
    assert len(S.from_param("created_at")) == 2


def test_sort_nulls_renders_in_sql() -> None:
    class S(SortSet[User]):
        email = asc(User.email, nulls="last")

    stmt = select(User).order_by(*S.from_param("email"))
    sql = str(stmt.compile(dialect=sqlite.dialect()))
    assert "NULLS LAST" in sql.upper()


def test_sort_unknown_field_raises_domain_error() -> None:
    with pytest.raises(InvalidSortError, match="Unknown sort field"):
        UserSorts.from_param("nope")


def test_sort_duplicate_alias_raises() -> None:
    with pytest.raises(InvalidSortError, match="Duplicate"):

        class _Bad(SortSet[User]):
            email = asc(User.email)
            created_at = desc(User.created_at, alias="email")
