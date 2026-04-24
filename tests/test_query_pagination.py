# Тесты Query: where, paginate, count, project.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import Repository

from tests.models import User, UserRead, UserStatus


async def _seed(session, n: int = 3) -> None:
    for i in range(n):
        u = User(
            id=uuid.uuid4(),
            email=f"u{i}@e.com",
            age=18 + i,
            status=UserStatus.ACTIVE,
            created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
            + datetime.timedelta(days=i),
        )
        session.add(u)
    await session.commit()


@pytest.mark.asyncio
async def test_to_list_and_where(session) -> None:
    await _seed(session, 2)
    repo = Repository(session, User)
    items = await repo.query().where(User.age >= 19).order_by(User.created_at.desc()).to_list()
    assert len(items) == 1
    assert items[0].age == 19


@pytest.mark.asyncio
async def test_where_if_and_count(session) -> None:
    await _seed(session, 2)
    repo = Repository(session, User)
    status: UserStatus | None = None
    q = repo.query().where_if(status is not None, User.status == status)
    c = await q.count()
    assert c == 2


@pytest.mark.asyncio
async def test_where_if_lazy_lambda_skips_eager_ge_none(session) -> None:
    await _seed(session, 1)
    repo = Repository(session, User)
    min_age: int | None = None
    # При «голом» User.age >= min_age в аргументе where_if Python всё равно строит выражение.
    # Lambda не вызывается, пока condition ложь — min_age is None, фильтр не применяется.
    c = await repo.query().where_if(min_age is not None, lambda: User.age >= min_age).count()
    assert c == 1
    min_age = 100
    c0 = await repo.query().where_if(min_age is not None, lambda: User.age >= min_age).count()  # type: ignore[operator, arg-type, misc]  # noqa: E501
    assert c0 == 0


@pytest.mark.asyncio
async def test_paginate_and_page_shape(session) -> None:
    await _seed(session, 5)
    repo = Repository(session, User)
    page = await repo.query().order_by(User.email.asc()).paginate(page=1, size=2)
    assert page.total == 5
    assert page.page == 1
    assert page.size == 2
    assert page.pages == 3
    assert len(page.items) == 2


@pytest.mark.asyncio
async def test_project_user_read(session) -> None:
    await _seed(session, 1)
    repo = Repository(session, User)
    rows = await repo.query().where(User.status == UserStatus.ACTIVE).project(UserRead).to_list()
    assert len(rows) == 1
    assert isinstance(rows[0], UserRead)
    assert rows[0].email == "u0@e.com"
