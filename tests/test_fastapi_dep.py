# FastAPI Depends(repo(...)).
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from queryforge.fastapi import repo
from queryforge.repository import Repository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi import Depends, FastAPI
from tests.models import Base, User


@pytest.mark.asyncio
async def test_repo_dep_injects_repository() -> None:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)

    async def get_session_real() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            yield s

    app = FastAPI()

    @app.get("/")
    async def root(
        users: Repository[User] = Depends(repo(User, session_dep=get_session_real)),
    ) -> dict[str, str]:
        assert users._model is User
        return {"ok": "1"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/")
    assert r.status_code == 200
    await eng.dispose()
