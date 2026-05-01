# Repository: получение, обновление, удаление, exists.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import EntityNotFound, Repository, UnknownUpdateFieldError
from sqlalchemy import select

from tests.models import User, UserStatus


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
async def test_update_changes_entity(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.update(u, email="n@b.com")
    assert u.email == "n@b.com"


@pytest.mark.asyncio
async def test_update_unknown_field_raises_in_strict_mode(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    with pytest.raises(UnknownUpdateFieldError, match="Unknown field"):
        await repo.update(u, emali="n@b.com")


@pytest.mark.asyncio
async def test_update_from_dict_unknown_field_allowed_when_requested(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.update_from_dict(u, {"emali": "n@b.com"}, ignore_unknown=True)
    assert u.email == "a@b.com"


@pytest.mark.asyncio
async def test_update_from_dict_unknown_field_raises_by_default(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    with pytest.raises(UnknownUpdateFieldError, match="Unknown field"):
        await repo.update_from_dict(u, {"emali": "n@b.com"})


@pytest.mark.asyncio
async def test_delete_removes_entity(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.delete(u)
    await session.commit()
    rows = (await session.execute(select(User))).scalars().all()
    assert rows == []
