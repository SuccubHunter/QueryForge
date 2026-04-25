# Join, include, selectin, joined на SQLAlchemy relationships.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import QueryForgeError, Repository
from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError

from tests.models import Order, Profile, User, UserRead, UserStatus


async def _user_with_children(session) -> User:
    u = User(
        id=uuid.uuid4(),
        email="parent@x.com",
        age=30,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.flush()
    session.add_all(
        [
            Order(user_id=u.id, title="a"),
            Order(user_id=u.id, title="b"),
        ]
    )
    session.add(Profile(user_id=u.id, bio="hi"))
    await session.commit()
    await session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_join_filters_by_related(session) -> None:
    u = await _user_with_children(session)
    repo = Repository(session, User)
    rows = await (
        repo.query().join(User.orders).where(Order.title == "a").order_by(User.email).to_list()
    )
    assert len(rows) == 1
    assert rows[0].id == u.id


@pytest.mark.asyncio
async def test_selectin_and_include_load_collection(session) -> None:
    await _user_with_children(session)
    repo = Repository(session, User)
    for q in (
        repo.query().selectin(User.orders),
        repo.query().include(User.orders),
    ):
        users = await q.order_by(User.email).to_list()
        assert len(users) == 1
        assert {o.title for o in users[0].orders} == {"a", "b"}


@pytest.mark.asyncio
async def test_joined_loads_profile(session) -> None:
    u = await _user_with_children(session)
    repo = Repository(session, User)
    users = await repo.query().joined(User.profile).where(User.id == u.id).to_list()
    assert len(users) == 1
    assert users[0].profile is not None
    assert users[0].profile.bio == "hi"


@pytest.mark.asyncio
async def test_without_eager_order_access_raises(session) -> None:
    u = await _user_with_children(session)
    repo = Repository(session, User)
    u2 = await repo.query().where(User.id == u.id).one()
    with pytest.raises(InvalidRequestError):
        _ = u2.orders


@pytest.mark.asyncio
async def test_count_ignores_loader_options(session) -> None:
    await _user_with_children(session)
    repo = Repository(session, User)
    c = await repo.query().selectin(User.orders).count()
    assert c == 1


@pytest.mark.asyncio
async def test_count_entity_with_join_counts_distinct_pk(session) -> None:
    await _user_with_children(session)
    repo = Repository(session, User)
    c = await repo.query().join(User.orders).count()
    assert c == 1


@pytest.mark.asyncio
async def test_include_with_project_raises_clear_error(session) -> None:
    await _user_with_children(session)
    repo = Repository(session, User)
    with pytest.raises(QueryForgeError, match="only with entity result queries"):
        await repo.query().project(UserRead).include(User.orders).to_list()


@pytest.mark.asyncio
async def test_include_with_select_raises_clear_error(session) -> None:
    await _user_with_children(session)
    repo = Repository(session, User)
    with pytest.raises(QueryForgeError, match="only with entity result queries"):
        await repo.query().select(User.email).include(User.orders).to_list()


@pytest.mark.asyncio
async def test_exists_skips_loader_options(session) -> None:
    u = await _user_with_children(session)
    repo = Repository(session, User)
    ok = await repo.query().selectin(User.orders).where(User.id == u.id).exists()
    assert ok is True


@pytest.mark.asyncio
async def test_from_statement_chains_selectin(session) -> None:
    u = await _user_with_children(session)
    repo = Repository(session, User)
    base = select(User).where(User.id == u.id)
    users = await repo.from_statement(base).selectin(User.orders).to_list()
    assert len(users) == 1
    assert {o.title for o in users[0].orders} == {"a", "b"}
