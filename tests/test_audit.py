# Аудит: контекст и слушатели.
from __future__ import annotations

import asyncio
import datetime
import uuid

import pytest
from queryforge import (
    Repository,
    SQLAlchemyAuditStorage,
    reset_audit_config,
)
from queryforge.audit import (
    AuditContext,
    add_audit_listener,
    configure_audit,
    get_audit_context,
    remove_audit_listener,
)
from sqlalchemy import select

from tests.models import AuditLog, User, UserStatus


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
    async with AuditContext(
        actor_id=uuid.uuid4(), reason="t", request_id="req-1", client_ip="10.0.0.1", user_agent="ua"
    ):
        ctx = get_audit_context()
        assert ctx.reason == "t"
        assert ctx.actor_id is not None
        assert ctx.request_id == "req-1"
        assert ctx.client_ip == "10.0.0.1"
        assert ctx.user_agent == "ua"


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
        await session.commit()
        await asyncio.sleep(0)
    finally:
        remove_audit_listener(h)
    assert any("updated" in str(x) for x in out)


@pytest.mark.asyncio
async def test_no_emit_on_rollback(session) -> None:
    u = await _make_user(session)
    out: list[object] = []

    async def h(payload: object) -> None:
        out.append(payload)

    add_audit_listener(h)
    try:
        repo = Repository(session, User)
        await repo.update(u, email="z@b.com")
        await session.rollback()
        await asyncio.sleep(0)
    finally:
        remove_audit_listener(h)
    assert not out


@pytest.mark.asyncio
async def test_request_metadata_in_payload(session) -> None:
    u = await _make_user(session)
    captured: list[object] = []

    async def h(payload: object) -> None:
        captured.append(payload)

    add_audit_listener(h)
    try:
        async with AuditContext(request_id="rid-99", client_ip="192.168.0.1", user_agent="curl/8"):
            repo = Repository(session, User)
            await repo.update(u, email="m@b.com")
            await session.commit()
            await asyncio.sleep(0)
    finally:
        remove_audit_listener(h)
    p = next(x for x in captured if isinstance(x, dict) and "updated" in str(x.get("action", "")))
    assert p["request_id"] == "rid-99"  # type: ignore[index]
    assert p["ip"] == "192.168.0.1"  # type: ignore[index]
    assert p["user_agent"] == "curl/8"  # type: ignore[index]


@pytest.mark.asyncio
async def test_listeners_isolated(session) -> None:
    u = await _make_user(session)
    log: list[str] = []

    def bad(p: object) -> None:  # noqa: ARG001
        raise RuntimeError("boom")

    async def good(payload: object) -> None:
        log.append(str(payload.get("action", "")))  # type: ignore[union-attr]

    add_audit_listener(bad)  # type: ignore[arg-type]
    add_audit_listener(good)
    try:
        repo = Repository(session, User)
        await repo.update(u, email="k@b.com")
        await session.commit()
        await asyncio.sleep(0)
    finally:
        remove_audit_listener(bad)  # type: ignore[arg-type]
        remove_audit_listener(good)
    assert any("user.updated" in e for e in log)


@pytest.mark.asyncio
async def test_outbox_table(session) -> None:
    u = await _make_user(session)
    storage = SQLAlchemyAuditStorage(AuditLog)
    configure_audit(deliver_to_listeners=False, outbox=storage)
    try:
        repo = Repository(session, User)
        await repo.update(u, email="out@b.com")
        await session.commit()
    finally:
        reset_audit_config()
    rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload.get("action") == "user.updated"  # type: ignore[union-attr]
    assert rows[0].payload.get("ip") is None  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_async_event_queue(session) -> None:
    u = await _make_user(session)
    q: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    configure_audit(deliver_to_listeners=False, async_event_queue=q, outbox=None)
    try:
        repo = Repository(session, User)
        await repo.update(u, email="q@b.com")
        await session.commit()
        await asyncio.sleep(0)
        p = await asyncio.wait_for(q.get(), timeout=1.0)
    finally:
        reset_audit_config()
    assert p.get("action") == "user.updated"  # type: ignore[union-attr]
