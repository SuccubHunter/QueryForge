# Маршруты пользователей: Repository, Query, project, paginate
from __future__ import annotations

import uuid

from queryforge import Page, Repository
from queryforge.fastapi import repo

from app.db import get_async_session
from app.models import User
from app.schemas import UserListQuery, UserRead
from fastapi import APIRouter, Depends, HTTPException, status

router = APIRouter(tags=["users"])


@router.get("/users", response_model=Page[UserRead])
async def list_users(
    q: UserListQuery = Depends(),
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> Page[UserRead]:
    return await (  # type: ignore[return-value, misc]
        users.query()
        .where_if(q.status is not None, User.status == q.status)
        .where_if(q.min_age is not None, User.age >= q.min_age)  # type: ignore[arg-type,operator]
        .order_by(User.created_at.desc())
        .project(UserRead)
        .paginate(page=q.page, size=q.size)
    )


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
