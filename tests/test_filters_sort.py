# FilterSet, SortSet.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import FilterSet, Repository, SortSet, asc, contains, desc, eq, gte

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
