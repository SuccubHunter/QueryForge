# project(DTO): alias, strict/loose, computed, nested, ProjectionError.
from __future__ import annotations

import datetime
import uuid

import pytest
from pydantic import BaseModel, Field, computed_field
from queryforge import ProjectionError, Repository

from tests.models import User, UserStatus


# Локальные вложенные DTO (должны быть в модуле, иначе get_type_hints в nested-проверке падает)
class _NestedChild(BaseModel):
    x: int


class _NestedParent(BaseModel):
    id: uuid.UUID
    inner: _NestedChild


@pytest.mark.asyncio
async def test_project_field_alias_maps_to_orm_column(session) -> None:
    """Field(alias=...) сопоставляет поле DTO с именем столбца ORM (например user_id → id)."""
    u = User(
        id=uuid.uuid4(),
        email="a@b.com",
        age=20,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()

    class UserAliased(BaseModel):
        user_id: uuid.UUID = Field(alias="id")
        email: str

    repo = Repository(session, User)
    rows = await repo.query().project(UserAliased).to_list()
    assert len(rows) == 1
    assert rows[0].user_id == u.id
    assert rows[0].email == "a@b.com"


@pytest.mark.asyncio
async def test_project_computed_field_not_selected(session) -> None:
    """computed_field не попадает в SELECT, вычисляется при валидации DTO."""

    class UserWithComputed(BaseModel):
        age: int
        email: str

        @computed_field  # type: ignore[prop-decorator]
        @property
        def age_plus_one(self) -> int:
            return self.age + 1

    u = User(
        id=uuid.uuid4(),
        email="c@d.com",
        age=40,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()

    repo = Repository(session, User)
    rows = await repo.query().project(UserWithComputed).to_list()
    assert len(rows) == 1
    assert rows[0].age == 40
    assert rows[0].age_plus_one == 41


@pytest.mark.asyncio
async def test_project_nested_dto_forbidden(session) -> None:
    """Вложенный BaseModel в поле — понятная ошибка (стратегия forbid)."""
    u = User(
        id=uuid.uuid4(),
        email="n@n.com",
        age=1,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()

    repo = Repository(session, User)
    with pytest.raises(ProjectionError) as exc_info:
        await repo.query().project(_NestedParent).to_list()
    assert "inner" in str(exc_info.value)


@pytest.mark.asyncio
async def test_project_strict_unknown_field(session) -> None:
    """Strict: обязательное поле без колонки в ORM — ProjectionError."""

    class Bad(BaseModel):
        id: uuid.UUID
        no_such_column: int

    u = User(
        id=uuid.uuid4(),
        email="s@s.com",
        age=1,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()

    repo = Repository(session, User)
    with pytest.raises(ProjectionError) as exc_info:
        await repo.query().project(Bad, mode="strict").to_list()
    err = exc_info.value
    assert isinstance(err, ProjectionError)
    assert "no_such_column" in err.unmapped_fields


@pytest.mark.asyncio
async def test_project_loose_partial_dto(session) -> None:
    """Loose: в SELECT только поля, объявленные в DTO (подмножество сущности)."""
    u = User(
        id=uuid.uuid4(),
        email="loose@x.com",
        age=99,
        status=UserStatus.ACTIVE,
        created_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
    )
    session.add(u)
    await session.commit()

    class UserPartial(BaseModel):
        id: uuid.UUID
        email: str

    repo = Repository(session, User)
    rows = await repo.query().project(UserPartial, mode="loose").to_list()
    assert len(rows) == 1
    assert rows[0].id == u.id
    assert rows[0].email == u.email
