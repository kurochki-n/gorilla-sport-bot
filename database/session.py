from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config_reader import get_settings
from database.base import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    await engine.dispose()
