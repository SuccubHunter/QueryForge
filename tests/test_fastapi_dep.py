# FastAPI Depends(repo(...)).
from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from queryforge import FilterSet, Page, SortSet, asc, desc, gte
from queryforge.fastapi import (
    QueryParams,
    filterset_query,
    page_response_type,
    pagination_params,
    query_params_annotated,
    repo,
    sort_params,
)
from queryforge.repository import Repository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from fastapi import Depends, FastAPI
from tests.models import Base, User, UserRead, UserStatus


class _AgeOnly(FilterSet[User]):
    min_age: int | None = gte(User.age)


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


@pytest.mark.asyncio
async def test_filterset_query_parses_and_openapi() -> None:
    app = FastAPI()

    @app.get("/f")
    async def with_filters(
        f: filterset_query(_AgeOnly),
    ) -> dict[str, int | None]:
        return {"m": f.min_age}

    openapi = app.openapi()
    params = openapi["paths"]["/f"]["get"].get("parameters", [])
    assert [p["name"] for p in params] == ["min_age"]

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/f", params={"min_age": "10"})
    assert r.status_code == 200
    assert r.json() == {"m": 10}


class _Filt(FilterSet[User]):
    min_age: int | None = gte(User.age)


class _Sort(SortSet[User]):
    email = asc(User.email)
    created = desc(User.created_at)


# Module-level alias: otherwise nested handlers with PEP 563 lack _ListUsersQ in globalns
_UsersQ = query_params_annotated(_Filt, _Sort)


def test_query_params_subscript_is_model_with_filters_sort_pagination() -> None:
    Qp = QueryParams[_Filt, _Sort]
    m = Qp(min_age=5, page=2, size=10, sort="-email")
    assert m.page == 2 and m.size == 10 and m.min_age == 5
    # email descending + stabilizing PK
    assert len(m.sort_terms()) == 2
    p = m.model_validate({})
    assert p.page == 1 and p.size == 20 and p.min_age is None


@pytest.mark.asyncio
async def test_query_params_annotated_openapi_and_list_users() -> None:
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, expire_on_commit=False, class_=AsyncSession)

    async def get_session_real() -> AsyncGenerator[AsyncSession, None]:
        async with factory() as s:
            yield s

    app = FastAPI()
    assert "items" in page_response_type(UserRead).model_json_schema().get("properties", {})

    @app.get("/users", response_model=Page[UserRead])
    async def list_users(
        q: _UsersQ,
        users: Repository[User] = Depends(repo(User, session_dep=get_session_real)),
    ) -> Page[UserRead]:
        return await (
            users.query().apply(q).sort(*q.sort_terms()).project(UserRead).paginate(q.page, q.size)
        )

    @app.get("/p")
    async def only_pag(p: pagination_params()) -> dict[str, int]:
        return {"page": p.page, "size": p.size}

    @app.get("/s", response_model=None)
    async def only_sort(s: sort_params()) -> dict[str, str | None]:
        t = s.order_terms(_Sort)
        return {"n": str(len(t)), "raw": s.sort}

    openapi = app.openapi()
    u_params = openapi["paths"]["/users"]["get"].get("parameters", [])
    names = sorted(p["name"] for p in u_params)
    assert names == ["min_age", "page", "size", "sort"]

    uid = str(uuid.uuid4())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        async with factory() as s_add:
            s_add.add(
                User(
                    id=uuid.UUID(uid),
                    email="a@b.c",
                    age=30,
                    status=UserStatus.ACTIVE,
                )
            )
            await s_add.commit()

        r0 = await ac.get("/p", params={"page": 3, "size": 15})
        assert r0.json() == {"page": 3, "size": 15}

        r1 = await ac.get(
            "/users", params={"page": 1, "size": 20, "min_age": "10", "sort": "email"}
        )
        assert r1.status_code == 200
        data = r1.json()
        assert data["total"] == 1
        assert data["page"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["email"] == "a@b.c"

        r422 = await ac.get("/users", params={"sort": "nope_field"})
        assert r422.status_code == 422

        r422_filter = await ac.get("/users", params={"min_age": "abc"})
        assert r422_filter.status_code == 422

        r422_sort_helper = await ac.get("/s", params={"sort": "nope_field"})
        assert r422_sort_helper.status_code == 422

    await eng.dispose()
