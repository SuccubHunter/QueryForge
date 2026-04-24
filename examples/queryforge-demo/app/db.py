# AsyncSession и фабрика сессий для FastAPI Depends
from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Пример: postgresql+asyncpg://user:pass@localhost:5432/demodb
_database_url = os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://queryforge:queryforge@localhost:5432/demodb"
)

engine = create_async_engine(_database_url, echo=False)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
