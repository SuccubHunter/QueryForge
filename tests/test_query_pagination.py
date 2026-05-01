# Query tests: where, paginate, count, project.
from __future__ import annotations

import datetime
import uuid

import pytest
from queryforge import EntityNotFound, InvalidPaginationError, InvalidQueryStateError, Repository

from tests.models import User, UserRead, UserStatus


async def _seed(session, n: int = 3) -> None:
    for i in range(n):
        u = User(
            id=uuid.uuid4(),
            email=f"u{i}@e.com",
            age=18 + i,
            status=UserStatus.ACTIVE,
            created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)
            + datetime.timedelta(days=i),
        )
        session.add(u)
    await session.commit()


@pytest.mark.asyncio
async def test_to_list_and_where(session) -> None:
    await _seed(session, 2)
    repo = Repository(session, User)
    items = await repo.query().where(User.age >= 19).order_by(User.created_at.desc()).to_list()
    assert len(items) == 1
    assert items[0].age == 19


@pytest.mark.asyncio
async def test_where_if_and_count(session) -> None:
    await _seed(session, 2)
    repo = Repository(session, User)
    status: UserStatus | None = None
    q = repo.query().where_if(status is not None, User.status == status)
    c = await q.count()
    assert c == 2


@pytest.mark.asyncio
async def test_where_if_lazy_lambda_skips_eager_ge_none(session) -> None:
    await _seed(session, 1)
    repo = Repository(session, User)
    min_age: int | None = None
    # With bare User.age >= min_age in a where_if argument, Python still builds the expression.
    # Lambda is not called while condition is false: min_age is None, filter is not applied.
    c = await repo.query().where_if(min_age is not None, lambda: User.age >= min_age).count()
    assert c == 1
    min_age = 100
    c0 = await repo.query().where_if(min_age is not None, lambda: User.age >= min_age).count()  # type: ignore[operator, arg-type, misc]  # noqa: E501
    assert c0 == 0


@pytest.mark.asyncio
async def test_optional_filter_helpers_skip_none_and_apply_values(session) -> None:
    await _seed(session, 3)
    repo = Repository(session, User)
    q0 = (
        repo.query()
        .eq_if_not_none(User.status, None)
        .gte_if_not_none(User.age, None)
        .lte_if_not_none(User.age, None)
        .contains_if_not_none(User.email, None)
    )
    assert await q0.count() == 3

    q1 = (
        repo.query()
        .eq_if_not_none(User.status, UserStatus.ACTIVE)
        .gte_if_not_none(User.age, 19)
        .lte_if_not_none(User.age, 20)
        .contains_if_not_none(User.email, "u")
    )
    rows = await q1.order_by(User.age.asc()).to_list()
    assert [r.age for r in rows] == [19, 20]


@pytest.mark.asyncio
async def test_where_not_none_is_immutable(session) -> None:
    await _seed(session, 2)
    repo = Repository(session, User)
    q0 = repo.query()
    q1 = q0.where_not_none(19, lambda value: User.age >= value)
    assert await q0.count() == 2
    assert await q1.count() == 1


@pytest.mark.asyncio
async def test_paginate_and_page_shape(session) -> None:
    await _seed(session, 5)
    repo = Repository(session, User)
    page = await repo.query().order_by(User.email.asc()).paginate(page=1, size=2)
    assert page.total == 5
    assert page.page == 1
    assert page.size == 2
    assert page.pages == 3
    assert len(page.items) == 2


@pytest.mark.asyncio
async def test_paginate_rejects_invalid_page_and_size(session) -> None:
    await _seed(session, 1)
    repo = Repository(session, User)
    with pytest.raises(InvalidPaginationError, match="page"):
        await repo.query().paginate(page=0, size=20)
    with pytest.raises(InvalidPaginationError, match="size"):
        await repo.query().paginate(page=1, size=0)
    with pytest.raises(InvalidPaginationError, match="page"):
        await repo.query().paginate(page="abc", size=20)  # type: ignore[arg-type]
    with pytest.raises(InvalidPaginationError, match="size"):
        await repo.query().paginate(page=1, size="abc")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_paginate_keeps_requested_out_of_range_page(session) -> None:
    await _seed(session, 2)
    repo = Repository(session, User)
    page = await repo.query().order_by(User.email.asc()).paginate(page=3, size=2)
    assert page.total == 2
    assert page.page == 3
    assert page.pages == 1
    assert page.items == []


@pytest.mark.asyncio
async def test_project_user_read(session) -> None:
    await _seed(session, 1)
    repo = Repository(session, User)
    rows = await repo.query().where(User.status == UserStatus.ACTIVE).project(UserRead).to_list()
    assert len(rows) == 1
    assert isinstance(rows[0], UserRead)
    assert rows[0].email == "u0@e.com"


@pytest.mark.asyncio
async def test_first_does_not_mutate_base_query(session) -> None:
    await _seed(session, 5)
    repo = Repository(session, User)
    q = repo.query()
    _ = await q.first()
    all_rows = await q.to_list()
    assert len(all_rows) == 5


@pytest.mark.asyncio
async def test_first_and_one_raise_domain_errors(session) -> None:
    repo = Repository(session, User)
    with pytest.raises(EntityNotFound):
        await repo.query().first()
    with pytest.raises(EntityNotFound):
        await repo.query().one()

    await _seed(session, 2)
    with pytest.raises(InvalidQueryStateError):
        await repo.query().one()
    with pytest.raises(InvalidQueryStateError):
        await repo.query().one_or_none()


@pytest.mark.asyncio
async def test_paginate_does_not_mutate_base_query(session) -> None:
    await _seed(session, 5)
    repo = Repository(session, User)
    q = repo.query().order_by(User.email.asc())
    _ = await q.paginate(page=1, size=2)
    total = await q.count()
    assert total == 5
    all_rows = await q.to_list()
    assert len(all_rows) == 5


@pytest.mark.asyncio
async def test_chained_queries_are_independent(session) -> None:
    await _seed(session, 3)
    repo = Repository(session, User)
    q0 = repo.query()
    q1 = q0.where(User.age >= 19)
    q2 = q1.limit(1)
    assert q0 is not q1
    assert q1 is not q2
    c0 = await q0.count()
    c1 = await q1.count()
    assert c0 == 3
    assert c1 == 2
    rows2 = await q2.to_list()
    assert len(rows2) == 1
