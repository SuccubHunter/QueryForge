# Репозиторий: get, update, delete, soft delete, exists.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import EntityNotFound, Repository
from sqlalchemy import select

from tests.models import NonSoftUser, User, UserStatus


async def _user(session) -> User:
    u = User(
        id=uuid.uuid4(),
        email="a@b.com",
        age=20,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()
    await session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_get_and_not_found(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    got = await repo.get(u.id)
    assert got.id == u.id
    with pytest.raises(EntityNotFound):
        await repo.get(uuid.uuid4())


@pytest.mark.asyncio
async def test_exists_and_query(session) -> None:
    await _user(session)
    repo = Repository(session, User)
    assert await repo.exists(User.email == "a@b.com") is True
    assert await repo.exists() is True


@pytest.mark.asyncio
async def test_from_statement(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    items = await repo.from_statement(select(User).where(User.id == u.id)).to_list()
    assert len(items) == 1


@pytest.mark.asyncio
async def test_update_emits_and_changes(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.update(u, email="n@b.com")
    assert u.email == "n@b.com"


@pytest.mark.asyncio
async def test_soft_delete_excluded_from_list(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.delete(u)
    all_rows = await repo.query().with_deleted().to_list()
    assert len(all_rows) == 1
    vis = await repo.query().to_list()
    assert len(vis) == 0
    only = await repo.query().only_deleted().to_list()
    assert len(only) == 1


@pytest.mark.asyncio
async def test_hard_delete_non_soft_model(session) -> None:
    session.add(NonSoftUser(name="x"))
    await session.commit()
    repo = Repository(session, NonSoftUser)
    n = (await session.execute(select(NonSoftUser))).scalars().first()
    assert n is not None
    await repo.delete(n)
    await session.commit()
    n2 = (await session.execute(select(NonSoftUser))).scalars().first()
    assert n2 is None
