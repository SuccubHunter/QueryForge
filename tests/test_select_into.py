# select(...) + into(DTO).
from __future__ import annotations

import datetime
import uuid

import pytest
from pydantic import BaseModel, Field
from queryforge import InvalidQueryStateError, ProjectionError, Repository

from tests.models import User, UserRead, UserStatus


async def _seed_user(session) -> User:
    u = User(
        id=uuid.uuid4(),
        email="a@b.com",
        age=20,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()
    return u


@pytest.mark.asyncio
async def test_select_into(session) -> None:
    await _seed_user(session)
    repo = Repository(session, User)
    rows = await (
        repo.query()
        .select(User.id, User.email, User.status, User.created_at)
        .into(UserRead)
        .to_list()
    )
    assert len(rows) == 1
    assert rows[0].email == "a@b.com"


@pytest.mark.asyncio
async def test_select_into_rejects_missing_required_columns(session) -> None:
    await _seed_user(session)
    repo = Repository(session, User)
    with pytest.raises(ProjectionError) as exc_info:
        await repo.query().select(User.id).into(UserRead).to_list()
    assert exc_info.value.unmapped_fields == ("created_at", "email", "status")


@pytest.mark.asyncio
async def test_select_into_with_labeled_columns(session) -> None:
    await _seed_user(session)
    repo = Repository(session, User)
    rows = await (
        repo.query()
        .select(
            User.id.label("id"),
            User.email.label("email"),
            User.status.label("status"),
            User.created_at.label("created_at"),
        )
        .into(UserRead)
        .to_list()
    )
    assert len(rows) == 1
    assert rows[0].email == "a@b.com"


@pytest.mark.asyncio
async def test_select_into_respects_dto_alias(session) -> None:
    u = await _seed_user(session)

    class UserAliased(BaseModel):
        user_id: uuid.UUID = Field(alias="id")
        email: str

    repo = Repository(session, User)
    rows = await repo.query().select(User.id, User.email).into(UserAliased).to_list()
    assert len(rows) == 1
    assert rows[0].user_id == u.id
    assert rows[0].email == "a@b.com"


@pytest.mark.asyncio
async def test_select_value_into_rejected(session) -> None:
    await _seed_user(session)
    repo = Repository(session, User)
    with pytest.raises(InvalidQueryStateError, match="select_value"):
        repo.query().select_value(User.email).into(UserRead)


@pytest.mark.asyncio
async def test_into_without_select_rejected(session) -> None:
    repo = Repository(session, User)
    with pytest.raises(InvalidQueryStateError, match="select"):
        repo.query().into(UserRead)


@pytest.mark.asyncio
async def test_select_into_wraps_pydantic_validation_error(session) -> None:
    await _seed_user(session)

    class BadTypes(BaseModel):
        id: uuid.UUID
        age: int

    repo = Repository(session, User)
    with pytest.raises(ProjectionError, match="current result shape"):
        await repo.query().select(User.id, User.email.label("age")).into(BadTypes).to_list()
