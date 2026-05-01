# Маршруты users: Repository, Query, project, paginate.
from __future__ import annotations

import uuid

from queryforge import EntityNotFound, Page, Repository
from queryforge.fastapi import repo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_async_session
from app.models import User
from app.schemas import UserEmailRead, UserListQuery, UserRead, UserUpdate
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

router = APIRouter(tags=["users"])


@router.get("/users", response_model=Page[UserRead])
async def list_users(
    q: UserListQuery,
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> Page[UserRead]:
    return await (
        users.query()
        .apply(q)
        .sort(*q.sort_terms())
        .project(UserRead)
        .paginate(q.page, q.size)
    )


@router.get("/users/emails", response_model=list[str])
async def list_user_emails(
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> list[str]:
    return await users.query().order_by(User.email.asc()).select_value(User.email).to_list()


@router.get("/users/selected", response_model=list[UserEmailRead])
async def list_selected_users(
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> list[UserEmailRead]:
    return await (
        users.query()
        .order_by(User.email.asc())
        .select(User.id, User.email)
        .into(UserEmailRead)
        .to_list()
    )


@router.get("/users/search/raw", response_model=list[UserRead])
async def search_users_raw(
    email: str = Query(min_length=1),
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> list[UserRead]:
    rows = await (
        users.from_statement(
            select(User).where(User.email.ilike(f"%{email}%")).order_by(User.created_at.desc())
        )
        .to_list()
    )
    return [UserRead.model_validate(row, from_attributes=True) for row in rows]


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
    return UserRead.model_validate(u, from_attributes=True)


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    session: AsyncSession = Depends(get_async_session),
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> UserRead:
    try:
        user = await users.get(user_id)
    except EntityNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from e

    await users.update(user, **body.model_dump(exclude_unset=True))
    await session.commit()
    return UserRead.model_validate(user, from_attributes=True)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    users: Repository[User] = Depends(
        repo(User, session_dep=get_async_session)  # noqa: B008
    ),
) -> Response:
    try:
        user = await users.get(user_id)
    except EntityNotFound as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from e

    await users.delete(user)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
