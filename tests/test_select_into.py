# select(...) + into(DTO).
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import Repository

from tests.models import User, UserRead, UserStatus


@pytest.mark.asyncio
async def test_select_into(session) -> None:
    u = User(
        id=uuid.uuid4(),
        email="a@b.com",
        age=20,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()
    repo = Repository(session, User)
    rows = await (
        repo.query()
        .select(User.id, User.email, User.status, User.created_at)
        .into(UserRead)
        .to_list()
    )
    assert len(rows) == 1
    assert rows[0].email == "a@b.com"
