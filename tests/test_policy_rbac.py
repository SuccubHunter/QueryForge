# Policy: read_scope, visible_for, allowed_by, FastAPI repo(read_scope=...).
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from queryforge import MissingPolicyError, Repository
from queryforge.fastapi import repo
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi import Depends, FastAPI
from tests.models import Base, OwnedItem


def _owner_scope(model: type[OwnedItem], user: object) -> object:
    return model.owner_id == user.id  # type: ignore[attr-defined, no-any-return]


class _OwnedPolicy:
    @staticmethod
    def read(user: object) -> object:
        return OwnedItem.owner_id == user.id  # type: ignore[attr-defined, no-any-return]


@pytest.mark.asyncio
async def test_visible_for_without_read_scope_raises(session) -> None:
    r = Repository(session, OwnedItem)
    u = type("U", (), {"id": uuid.uuid4()})()
    with pytest.raises(MissingPolicyError):
        await r.query().visible_for(u).to_list()


@pytest.mark.asyncio
async def test_visible_for_filters_by_read_scope(session) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            OwnedItem(owner_id=a, label="mine"),
            OwnedItem(owner_id=b, label="other"),
        ]
    )
    await session.commit()
    r = Repository(session, OwnedItem, read_scope=_owner_scope)
    u = type("U", (), {"id": a})()
    rows = await r.query().visible_for(u).to_list()
    assert len(rows) == 1
    assert rows[0].label == "mine"


@pytest.mark.asyncio
async def test_allowed_by_action(session) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            OwnedItem(owner_id=a, label="mine"),
            OwnedItem(owner_id=b, label="other"),
        ]
    )
    await session.commit()
    r = Repository(session, OwnedItem)
    u = type("U", (), {"id": a})()
    rows = await r.query().allowed_by(_OwnedPolicy.read, u).to_list()
    assert {x.label for x in rows} == {"mine"}


@pytest.mark.asyncio
async def test_from_statement_keeps_read_scope(session) -> None:
    from sqlalchemy import select

    a, b = uuid.uuid4(), uuid.uuid4()
    session.add_all([OwnedItem(owner_id=a, label="x"), OwnedItem(owner_id=b, label="y")])
    await session.commit()
    r = Repository(session, OwnedItem, read_scope=_owner_scope)
    u = type("U", (), {"id": a})()
    q = r.from_statement(select(OwnedItem))
    rows = await q.visible_for(u).to_list()
    assert len(rows) == 1
    assert rows[0].label == "x"


@pytest.mark.asyncio
async def test_fastapi_repo_read_scope_visible_for() -> None:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)

    async def get_session_real() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            yield s

    uid = uuid.uuid4()
    other = uuid.uuid4()
    async with factory() as s0:
        s0.add_all(
            [
                OwnedItem(owner_id=uid, label="ok"),
                OwnedItem(owner_id=other, label="no"),
            ]
        )
        await s0.commit()

    app = FastAPI()

    @app.get("/items")
    async def list_items(
        users: Repository[OwnedItem] = Depends(
            repo(OwnedItem, session_dep=get_session_real, read_scope=_owner_scope)
        ),
    ) -> dict[str, int | list[str]]:
        u = type("U", (), {"id": uid})()
        rows = await users.query().visible_for(u).to_list()
        return {"n": len(rows), "labels": [r.label for r in rows]}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/items")
    assert r.status_code == 200
    assert r.json() == {"n": 1, "labels": ["ok"]}
    await eng.dispose()
