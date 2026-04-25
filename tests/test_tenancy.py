# Multi-tenancy: TenantContext, for_tenant, with_all_tenants, Repository.
from __future__ import annotations

import uuid

import pytest
from queryforge import (
    EntityNotFound,
    MissingTenantError,
    QueryForgeError,
    Repository,
    TenantContext,
)
from sqlalchemy import select

from tests.models import TenantItem


@pytest.mark.asyncio
async def test_query_requires_tenant_context_or_for_tenant(session) -> None:
    t1 = uuid.uuid4()
    item = TenantItem(tenant_id=t1, name="a")
    session.add(item)
    await session.commit()

    repo = Repository(session, TenantItem)
    with pytest.raises(MissingTenantError):
        await repo.query().to_list()
    out = await repo.query().for_tenant(t1).to_list()
    assert len(out) == 1
    assert out[0].name == "a"


@pytest.mark.asyncio
async def test_tenant_context_filters_query(session) -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            TenantItem(tenant_id=t1, name="a"),
            TenantItem(tenant_id=t2, name="b"),
        ]
    )
    await session.commit()

    repo = Repository(session, TenantItem)
    async with TenantContext(t1):
        rows = await repo.query().to_list()
    assert {r.name for r in rows} == {"a"}


@pytest.mark.asyncio
async def test_add_sets_tenant_from_context(session) -> None:
    t1 = uuid.uuid4()
    repo = Repository(session, TenantItem)
    row = TenantItem()
    row.name = "x"
    async with TenantContext(t1):
        await repo.add(row)
    await session.commit()
    r = (await session.execute(select(TenantItem).where(TenantItem.name == "x"))).scalars().first()
    assert r is not None
    assert r.tenant_id == t1


@pytest.mark.asyncio
async def test_add_missing_tenant_raises(session) -> None:
    repo = Repository(session, TenantItem)
    row = TenantItem()
    row.name = "n"
    with pytest.raises(MissingTenantError):
        await repo.add(row)


@pytest.mark.asyncio
async def test_add_explicit_tenant_without_context(session) -> None:
    t1 = uuid.uuid4()
    repo = Repository(session, TenantItem)
    await repo.add(TenantItem(tenant_id=t1, name="e"))
    await session.commit()
    n = (await session.execute(select(TenantItem))).scalars().first()
    assert n is not None
    assert n.tenant_id == t1


@pytest.mark.asyncio
async def test_get_enforces_tenant(session) -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    item = TenantItem(tenant_id=t1, name="g")
    session.add(item)
    await session.commit()
    iid = item.id

    repo = Repository(session, TenantItem)
    with pytest.raises(MissingTenantError):
        await repo.get(iid)

    async with TenantContext(t2):
        with pytest.raises(EntityNotFound):
            await repo.get(iid)

    async with TenantContext(t1):
        got = await repo.get(iid)
    assert got.id == iid


@pytest.mark.asyncio
async def test_with_all_tenants_sees_all(session) -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            TenantItem(tenant_id=t1, name="1"),
            TenantItem(tenant_id=t2, name="2"),
        ]
    )
    await session.commit()
    repo = Repository(session, TenantItem)
    all_rows = await repo.query().with_all_tenants().to_list()
    assert len(all_rows) == 2


@pytest.mark.asyncio
async def test_update_rejects_tenant_id_change(session) -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    item = TenantItem(tenant_id=t1, name="u")
    session.add(item)
    await session.commit()
    repo = Repository(session, TenantItem)
    async with TenantContext(t1):
        with pytest.raises(QueryForgeError):
            await repo.update(item, tenant_id=t2)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_delete_requires_tenant_context(session) -> None:
    t1 = uuid.uuid4()
    item = TenantItem(tenant_id=t1, name="d")
    session.add(item)
    await session.commit()
    repo = Repository(session, TenantItem)
    with pytest.raises(MissingTenantError):
        await repo.hard_delete(item)


@pytest.mark.asyncio
async def test_from_statement_no_auto_tenant_filter(session) -> None:
    t1, t2 = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            TenantItem(tenant_id=t1, name="x"),
            TenantItem(tenant_id=t2, name="y"),
        ]
    )
    await session.commit()
    repo = Repository(session, TenantItem)
    rows = await repo.from_statement(select(TenantItem)).to_list()
    assert len(rows) == 2
