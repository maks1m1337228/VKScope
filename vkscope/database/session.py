"""Асинхронные сессии SQLAlchemy + инициализация схемы БД."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from database.models import Base

engine = create_async_engine(
    settings.postgres_dsn,
    echo=False,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_db() -> None:
    """Создаёт таблицы и добавляет новые колонки в существующую БД."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS access_token VARCHAR(2048)")
        )
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_updated_at TIMESTAMPTZ")
        )
        await conn.execute(
            text(
                "ALTER TABLE recommended_groups "
                "ADD COLUMN IF NOT EXISTS photo_vk_id VARCHAR(64) DEFAULT ''"
            )
        )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
