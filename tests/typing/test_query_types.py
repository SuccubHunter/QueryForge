# Статическая типизация Query: assert_type согласован с pyright.
from __future__ import annotations

from typing import Any, assert_type

import pytest
from queryforge import Repository
from queryforge.pagination import Page

from tests.models import User, UserRead, UserStatus


@pytest.mark.asyncio
async def test_query_to_list_model(session) -> None:
    repo = Repository(session, User)
    users = await repo.query().to_list()
    assert_type(users, list[User])


@pytest.mark.asyncio
async def test_query_first_model(session) -> None:
    u = User(email="a@b.com", age=1, status=UserStatus.ACTIVE)
    session.add(u)
    await session.commit()
    repo = Repository(session, User)
    first = await repo.query().first()
    assert_type(first, User)


@pytest.mark.asyncio
async def test_query_project_dto(session) -> None:
    repo = Repository(session, User)
    items = await repo.query().project(UserRead).to_list()
    assert_type(items, list[UserRead])


@pytest.mark.asyncio
async def test_query_project_first_one(session) -> None:
    u = User(email="a@b.com", age=1, status=UserStatus.ACTIVE)
    session.add(u)
    await session.commit()
    repo = Repository(session, User)
    first = await repo.query().project(UserRead).first()
    assert_type(first, UserRead)
    one = await repo.query().project(UserRead).one()
    assert_type(one, UserRead)
    one_n = await repo.query().project(UserRead).one_or_none()
    assert_type(one_n, UserRead | None)
    first_n = await repo.query().project(UserRead).first_or_none()
    assert_type(first_n, UserRead | None)


@pytest.mark.asyncio
async def test_query_paginate_projected(session) -> None:
    repo = Repository(session, User)
    page = await repo.query().project(UserRead).paginate(1, 20)
    assert_type(page, Page[UserRead])


@pytest.mark.asyncio
async def test_query_select_two_columns(session) -> None:
    """Рантайм + узкая сигнатура select(a, b) -> tuple[Any, Any]."""
    repo = Repository(session, User)
    u = User(
        email="t@t.com",
        age=1,
        status=UserStatus.ACTIVE,
    )
    session.add(u)
    await session.commit()
    rows = await repo.query().select(User.id, User.email).to_list()
    assert_type(rows, list[tuple[Any, Any]])
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_from_statement_any(session) -> None:
    from sqlalchemy import select

    u = User(email="a@b.com", age=1, status=UserStatus.ACTIVE)
    session.add(u)
    await session.commit()
    repo = Repository(session, User)
    items = await repo.from_statement(select(User).where(User.id == u.id)).to_list()
    assert_type(items, list[Any])
