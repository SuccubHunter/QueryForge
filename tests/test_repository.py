# Репозиторий: get, update, delete, soft delete, exists.
from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest
from queryforge import (
    AlreadySoftDeleted,
    EntityNotFound,
    NotSoftDeleted,
    Repository,
    add_audit_listener,
    remove_audit_listener,
    set_soft_delete_policy,
)
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
    await repo.delete(u, reason="cleanup")
    all_rows = await repo.query().with_deleted().to_list()
    assert len(all_rows) == 1
    vis = await repo.query().to_list()
    assert len(vis) == 0
    only = await repo.query().only_deleted().to_list()
    assert len(only) == 1
    assert u.deleted_by is None
    assert u.delete_reason == "cleanup"


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


@pytest.mark.asyncio
async def test_double_soft_delete_raises(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.delete(u)
    with pytest.raises(AlreadySoftDeleted):
        await repo.delete(u)


@pytest.mark.asyncio
async def test_restore_after_soft_delete(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.delete(u, reason="t")
    assert u.deleted_at is not None
    await repo.restore(u)
    assert u.deleted_at is None
    assert u.delete_reason is None
    vis = await repo.query().to_list()
    assert len(vis) == 1


@pytest.mark.asyncio
async def test_restore_active_raises(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    with pytest.raises(NotSoftDeleted):
        await repo.restore(u)


@pytest.mark.asyncio
async def test_restore_non_soft_model_raises(session) -> None:
    session.add(NonSoftUser(name="n"))
    await session.commit()
    repo = Repository(session, NonSoftUser)
    n = (await session.execute(select(NonSoftUser))).scalars().first()
    with pytest.raises(NotSoftDeleted):
        await repo.restore(n)


@pytest.mark.asyncio
async def test_hard_delete_soft_model(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    await repo.hard_delete(u)
    await session.commit()
    n = (await session.execute(select(User))).scalars().first()
    assert n is None


@pytest.mark.asyncio
async def test_delete_deleted_by_param(session) -> None:
    u = await _user(session)
    repo = Repository(session, User)
    actor = uuid.uuid4()
    await repo.delete(u, deleted_by=actor, reason="spam")
    assert u.deleted_by == str(actor)
    assert u.delete_reason == "spam"


@pytest.mark.asyncio
async def test_global_soft_delete_policy(session) -> None:
    u = await _user(session)
    calls: list[tuple[str, str]] = []

    async def pol(op, model, _entity: object) -> None:
        calls.append((op, model.__name__))

    set_soft_delete_policy(pol)
    try:
        repo = Repository(session, User)
        await repo.delete(u, reason="r")
        assert ("soft_delete", "User") in calls
        await repo.restore(u)
        assert ("restore", "User") in calls
        await repo.hard_delete(u)
        assert ("hard_delete", "User") in calls
    finally:
        set_soft_delete_policy(None)


@pytest.mark.asyncio
async def test_delete_audit_includes_reason(session) -> None:
    u = await _user(session)
    payloads: list[object] = []

    async def h(p: object) -> None:
        payloads.append(p)

    add_audit_listener(h)
    try:
        repo = Repository(session, User)
        await repo.delete(u, reason="spam")
        await session.commit()
        await asyncio.sleep(0)
    finally:
        remove_audit_listener(h)
    found = [x for x in payloads if isinstance(x, dict) and x.get("action", "").endswith("deleted")]
    assert len(found) == 1
    assert found[0]["reason"] == "spam"
