# Маршруты пользователей: Repository, Query, project, paginate
#
# Ниже в комментариях — тот же сценарий «вручную» на SQLAlchemy 2.0 + Pydantic, без queryforge
# (условия, пагинация, проекция, мягкое удаление дублируются в каждом эндпоинте).
from __future__ import annotations

import uuid

from queryforge import Page, Repository
from queryforge.fastapi import repo

from app.db import get_async_session
from app.models import User
from app.schemas import UserListQuery, UserRead
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(tags=["users"])


# --- GET /users ---
#
# Примерно то же без библиотеки (идея, не копипаста в рантайм):
#
#     from math import ceil
#     from sqlalchemy import func, select
#     from sqlalchemy.ext.asyncio import AsyncSession
#
#     @router.get("/users", response_model=Page[UserRead])
#     async def list_users(
#         q: UserListQuery = Depends(),
#         session: AsyncSession = Depends(get_async_session),
#     ) -> Page[UserRead]:
#         wheres: list = [User.deleted_at.is_(None)]  # как SoftDeleteMixin в Query
#         if q.status is not None:
#             wheres.append(User.status == q.status)
#         if q.min_age is not None:
#             wheres.append(User.age >= q.min_age)
#
#         count_stmt = select(func.count()).select_from(User).where(*wheres)
#         total = (await session.execute(count_stmt)).scalar_one()
#
#         offset = (q.page - 1) * q.size
#         stmt = (
#             select(User)
#             .where(*wheres)
#             .order_by(User.created_at.desc())
#             .offset(offset)
#             .limit(q.size)
#         )
#         rows = (await session.execute(stmt)).scalars().unique().all()
#         items = [UserRead.model_validate(r) for r in rows]
#         pages = ceil(total / q.size) if q.size and total else 0
#         return Page(items=items, total=total, page=q.page, size=q.size, pages=pages)
@router.get("/users", response_model=Page[UserRead])
async def list_users(
    q: UserListQuery = Depends(),
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> Page[UserRead]:
    # where_if: для опциональных сравнений с параметрами из запроса используйте lambda,
    # иначе Python вычислит (например) User.age >= q.min_age до вызова where_if — при
    # q.min_age is None SQLAlchemy выдаст ArgumentError.
    # Цепочка: Query[User, User] → project(UserRead) → Query[User, UserRead];
    # await paginate → Page[UserRead].
    result: Page[UserRead] = await (
        users.query()
        .where_if(
            q.status is not None,
            lambda: User.status == q.status,  # type: ignore[arg-type]
        )
        .where_if(
            q.min_age is not None,
            lambda: User.age >= q.min_age,  # type: ignore[operator, arg-type, misc]
        )
        .order_by(User.created_at.desc())
        .project(UserRead)
        .paginate(page=q.page, size=q.size)
    )
    return result


# --- GET /users/{user_id} ---
#
# Примерно то же без библиотеки:
#
#     @router.get("/users/{user_id}", response_model=UserRead)
#     async def get_user(
#         user_id: uuid.UUID,
#         session: AsyncSession = Depends(get_async_session),
#     ) -> UserRead:
#         u = await session.get(User, user_id)
#         if u is None or u.deleted_at is not None:
#             raise HTTPException(status_code=404, detail="User not found")
#         return UserRead.model_validate(u)
#
#     # либо явный select + одна строка:
#     # stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
#     # u = (await session.execute(stmt)).scalars().one_or_none()
@router.get("/users/{user_id}", response_model=UserRead)
async def get_user(
    user_id: uuid.UUID,
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> UserRead:
    u = await users.get_or_none(user_id)
    if u is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserRead.model_validate(u)
