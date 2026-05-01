# QueryForge

[![CI](https://github.com/SuccubHunter/QueryForge/actions/workflows/ci.yml/badge.svg)](https://github.com/SuccubHunter/QueryForge/actions/workflows/ci.yml)
[![Codecov](https://codecov.io/gh/SuccubHunter/QueryForge/graph/badge.svg)](https://codecov.io/gh/SuccubHunter/QueryForge)
[![PyPI](https://img.shields.io/pypi/v/queryforge.svg)](https://pypi.org/project/queryforge/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg)](https://github.com/SuccubHunter/QueryForge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Typing: typed](https://img.shields.io/badge/typing-typed-blue.svg)](queryforge/py.typed)

> Status: Alpha. API is usable, but may change before 1.0.
> Recommended for experiments, internal tools and early adopters.

QueryForge is a typed application query/repository layer on top of SQLAlchemy 2.0 for FastAPI and backend applications.

QueryForge is not an ORM and does not replace SQLAlchemy. It is an application layer on top of SQLAlchemy 2.0: SQLAlchemy stays visible, composable and available as the escape hatch for complex SQL.

Primary use case: build typed paginated FastAPI endpoints with SQLAlchemy in minutes, without writing the same query boilerplate again.

## What QueryForge Covers

QueryForge competes with repetitive application-level boilerplate, not with SQLAlchemy:

- base repository;
- parsing query params;
- filters and sorting;
- pagination;
- DTO projection.

You can adopt the library one layer at a time:

| Level | What you use |
| --- | --- |
| Core | `Repository`, immutable `Query`, typed terminals, `Page` |
| API layer | `FilterSet`, `SortSet`, FastAPI `QueryParams` helpers |

## Before / After

```python
# Before: raw SQLAlchemy code usually repeats filters, count, pagination and DTO mapping.
stmt = (
    select(User)
    .where(User.status == q.status)
    .order_by(User.created_at.desc())
    .offset((q.page - 1) * q.size)
    .limit(q.size)
)
rows = (await session.execute(stmt)).scalars().unique().all()
items = [UserRead.model_validate(row, from_attributes=True) for row in rows]
```

```python
# After: QueryForge keeps the SQLAlchemy model visible and removes application boilerplate.
return await (
    users.query()
    .apply(q)
    .sort(*q.sort_terms())
    .project(UserRead)
    .paginate(q.page, q.size)
)
```

## Installation

```bash
pip install queryforge
pip install queryforge[fastapi]
```

For local development or checkout install checks:

```bash
pip install .[dev]
pip install .[fastapi]
```

## Quickstart

The minimal example below shows a SQLAlchemy model, Pydantic DTO, repository, filter, sort, projection and pagination. It is the same core pipeline used by `examples/queryforge-demo`.
This is a schematic copy-paste skeleton: `User`, `UserRead`, `UserStatus`, database setup and `AsyncSession` lifecycle are application-defined. For a runnable FastAPI app, use [`examples/queryforge-demo`](examples/queryforge-demo).

```python
from __future__ import annotations

import datetime
import enum
import uuid
from typing import ClassVar

from pydantic import BaseModel, ConfigDict
from queryforge import FilterSet, Page, Repository, SortSet, asc, contains, desc, eq, gte
from sqlalchemy import DateTime, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class User(Base):
    __tablename__: ClassVar[str] = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    age: Mapped[int] = mapped_column()
    status: Mapped[UserStatus] = mapped_column(String(32))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.datetime.now(datetime.UTC),
    )


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    age: int
    status: UserStatus
    created_at: datetime.datetime


class UserFilters(FilterSet[User]):
    status: UserStatus | None = eq(User.status)
    min_age: int | None = gte(User.age)
    email: str | None = contains(User.email)


class UserSorts(SortSet[User]):
    __default_sort__ = "-created_at"
    email = asc(User.email)
    created_at = desc(User.created_at, alias="created")


async def list_users(
    session: AsyncSession,
    filters: UserFilters,
    page: int = 1,
    size: int = 20,
) -> Page[UserRead]:
    users = Repository(session, User)
    return await (
        users.query()
        .apply(filters)
        .sort(*UserSorts.from_param("-created_at"))
        .project(UserRead)
        .paginate(page, size)
    )
```

Minimal usage without FastAPI:

```python
items = await (
    users.query()
    .where(User.status == UserStatus.ACTIVE)
    .project(UserRead)
    .paginate(1, 20)
)
```

## Typed Query Examples

`Query[ModelT, ResultT]` changes the result type as the pipeline is built:

```python
users = await repo.query().to_list()
# list[User]

items = await repo.query().project(UserRead).to_list()
# list[UserRead]

page = await repo.query().project(UserRead).paginate(1, 20)
# Page[UserRead]

rows = await repo.query().select(User.id, User.email).to_list()
# list[tuple[UUID, str]]

emails = await repo.query().select_value(User.email).to_list()
# list[str]

selected = await repo.query().select(User.id, User.email).into(UserEmailRead).to_list()
# list[UserEmailRead]
```

`Query` immutable: `where`, `sort`, `project`, `select`, `limit`, `offset`, `include`, `selectin` and `joined` return a new query object instead of mutating the previous one.

## FastAPI Example

This example assumes the `User`, `UserRead` and `UserStatus` types from the quickstart, plus an application-defined `get_async_session` dependency.

```python
from __future__ import annotations

from typing import AsyncIterator

from fastapi import APIRouter, Depends
from queryforge import FilterSet, Page, Repository, SortSet, asc, contains, desc, eq, gte
from queryforge.fastapi import query_params_annotated, repo, set_session_dep
from sqlalchemy.ext.asyncio import AsyncSession


async def get_async_session() -> AsyncIterator[AsyncSession]:
    ...


set_session_dep(get_async_session)
router = APIRouter(tags=["users"])


class UserFilters(FilterSet[User]):
    status: UserStatus | None = eq(User.status)
    min_age: int | None = gte(User.age)
    email: str | None = contains(User.email)


class UserSorts(SortSet[User]):
    __default_sort__ = "-created_at"
    email = asc(User.email)
    created_at = desc(User.created_at, alias="created")


UsersQuery = query_params_annotated(UserFilters, UserSorts)


@router.get("/users", response_model=Page[UserRead])
async def list_users(
    q: UsersQuery,
    users: Repository[User] = Depends(repo(User)),
) -> Page[UserRead]:
    return await (
        users.query()
        .apply(q)
        .sort(*q.sort_terms())
        .project(UserRead)
        .paginate(q.page, q.size)
    )
```

FastAPI helpers:

- `set_session_dep(get_session)` stores a default SQLAlchemy session dependency for `repo(Model)`;
- `repo(User)` creates `Depends` for `Repository[User]`;
- `FilterSet` validates filter query params with Pydantic v2;
- `SortSet` parses `sort=-created,email`;
- `query_params_annotated(FilterSet, SortSet)` combines filters, `page`, `size` and `sort`;
- `Page[UserRead]` is the typed paginated response model.

Runnable FastAPI example with database setup, routes and Docker files: [`examples/queryforge-demo`](examples/queryforge-demo).

## Core Concepts

- `Repository[M]` wraps an `AsyncSession` and a SQLAlchemy model. It exposes `query`, `get`, `get_or_none`, `exists`, `add`, `update`, `update_from_dict`, `delete` and `from_statement`.
- `Query[ModelT, ResultT]` is an immutable query pipeline. Entity queries start as `Query[User, User]`; projection and selection change `ResultT`.
- `FilterSet[M]` declares reusable filters with helpers such as `eq`, `gte`, `lte` and `contains`.
- `SortSet[M]` declares allowed sort fields, aliases, default sort and primary-key tie breakers.
- `Page[T]` contains `items`, `total`, `page`, `size` and `pages`.
- `project(DTO)` maps ORM rows to Pydantic DTOs by field names and aliases.
- `select(...)`, `select_value(...)` and `into(DTO)` cover typed column selection and DTO mapping from selected columns.
- `include`, `selectin` and `joined` expose common SQLAlchemy eager-loading strategies for entity-result queries.

## Stable And Experimental Surface

Stable alpha surface:

- repository CRUD/query operations;
- immutable query pipeline;
- filters, sorting and pagination;
- Pydantic projection for flat DTOs;
- FastAPI dependency helpers.

Experimental or intentionally narrow:

- advanced SQL expression typing in `select()`;
- nested DTO SQL projection.

## Escape Hatches And Limitations

1. QueryForge does not replace SQLAlchemy. Complex analytical queries are better written directly with SQLAlchemy.
2. `Repository.from_statement()` is the raw SQLAlchemy escape hatch for application-specific statements.
3. Nested DTO SQL projection is not the primary goal. Use `project(..., nested="orm")` when ORM-based nested DTO assembly is acceptable.
4. Loader options work with entity-result queries and with `project(..., nested="orm")`; using loader options after `project`, `select`, `select_value` or `into` raises `InvalidQueryStateError`.
5. Complex SQLAlchemy expressions in `select()` may degrade to `Any` in static typing.

## Development

QueryForge uses Python 3.11+ and Poetry. The local checks intentionally match GitHub Actions CI:

```bash
poetry install
poetry run ruff check .
poetry run pyright
poetry run pytest -q
poetry run python -m build
poetry run twine check dist/*
```

Package install checks:

```bash
pip install .
pip install .[fastapi]
pip install .[dev]
```

CI runs the same checks on Python 3.11 and 3.12 for pull requests, pushes to `main` / `master`, and manual `workflow_dispatch`.

See [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## Release process

Publishing uses GitHub Actions and PyPI Trusted Publishing (OIDC). Do not store PyPI or TestPyPI tokens in the repository.

Before the first release, configure trusted publishers:

- PyPI project `queryforge`: repository `SuccubHunter/QueryForge`, workflow `.github/workflows/publish.yml`, environment `pypi`;
- TestPyPI project `queryforge`: repository `SuccubHunter/QueryForge`, workflow `.github/workflows/publish.yml`, environment `testpypi`.

1. Update version in `pyproject.toml` and `queryforge/__init__.py`.

2. Run local checks:

```bash
poetry install
poetry run ruff check .
poetry run pyright
poetry run pytest -q
poetry run python -m build
poetry run twine check dist/*
```

3. Publish to TestPyPI via `workflow_dispatch` in the `Publish` GitHub Actions workflow.

4. Verify TestPyPI install in a clean environment:

```bash
python -m venv /tmp/qf-test
source /tmp/qf-test/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  queryforge==0.1.0
python -c "import queryforge; print(queryforge.__version__)"
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  "queryforge[fastapi]==0.1.0"
```

5. Create and push release tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

6. Verify PyPI release:

```bash
python -m venv /tmp/qf-pypi
source /tmp/qf-pypi/bin/activate
python -m pip install --upgrade pip
python -m pip install "queryforge==0.1.0"
python -c "import queryforge; print(queryforge.__version__)"
```

The `Publish` workflow publishes to production PyPI only from tags matching `v*.*.*`. The workflow also verifies that the tag version matches both `pyproject.toml` and `queryforge.__version__`.

Manual pre-tag command summary:

```bash
poetry install
poetry run ruff check .
poetry run pyright
poetry run pytest -q
poetry run python -m build
poetry run twine check dist/*
```

## Package Metadata

The package metadata is defined in `pyproject.toml`:

- package name: `queryforge`;
- Python: `>=3.11`;
- license: MIT;
- repository: `https://github.com/SuccubHunter/QueryForge`;
- classifier: `Typing :: Typed`;
- extras: `fastapi`, `dev`;
- `queryforge/py.typed` is included in wheel and sdist.

## License

MIT
