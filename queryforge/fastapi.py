# FastAPI: фабрика Depends(Repository) с подставляемой зависимостью сессии.
from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from queryforge.repository import Repository

M = TypeVar("M")

# Глобальная зависимость: установите через set_session_dep(get_async_session).
_default_session_dep: Any = None


def set_session_dep(session_dep: Any) -> None:
    """Сохраняет Depends-фабрику сессии для repo(model) без session_dep."""
    global _default_session_dep
    _default_session_dep = session_dep


def get_session_dep() -> Any:
    return _default_session_dep


def repo(
    model: type[M],
    *,
    session_dep: Any | None = None,
) -> Any:
    """Session -> Repository. Пример: Depends(repo(User, session_dep=get_session))."""
    from fastapi import Depends  # type: ignore[import-untyped, import-not-found]

    dep = session_dep or _default_session_dep
    if dep is None:
        msg = "Укажите session_dep=... в repo() или set_session_dep(Depends get_session)."
        raise RuntimeError(msg)

    async def _inner(
        session: AsyncSession = Depends(dep),
    ) -> Repository[M]:
        return Repository(session, model)

    return _inner
