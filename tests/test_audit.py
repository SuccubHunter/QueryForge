# Аудит: контекст и слушатели.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import Repository
from queryforge.audit import (
    AuditContext,
    add_audit_listener,
    get_audit_context,
    remove_audit_listener,
)

from tests.models import User, UserStatus


async def _make_user(session) -> User:
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
async def test_audit_context_var(session) -> None:
    async with AuditContext(actor_id=uuid.uuid4(), reason="t"):
        aid, r = get_audit_context()
        assert r == "t"
        assert aid is not None


@pytest.mark.asyncio
async def test_update_emits_to_listener(session) -> None:
    u = await _make_user(session)
    out: list[object] = []

    async def h(payload: object) -> None:
        out.append(payload)

    add_audit_listener(h)
    try:
        repo = Repository(session, User)
        await repo.update(u, email="z@b.com")
    finally:
        remove_audit_listener(h)
    assert any("updated" in str(x) for x in out)
