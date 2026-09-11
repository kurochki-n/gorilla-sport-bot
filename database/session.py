from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config_reader import get_settings
from database import models  # noqa: F401  # регистрирует модели в Base.metadata
from database.base import Base

settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

        # create_all не добавляет новые столбцы в уже существующие таблицы.
        # Эта небольшая миграция сохраняет совместимость с базами старых установок.
        exercise_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("exercises")
            }
        )
        missing_columns = {
            "description": "TEXT",
            "media_file_id": "VARCHAR(512)",
            "media_type": "VARCHAR(20)",
        }
        for column_name, column_type in missing_columns.items():
            if column_name not in exercise_columns:
                await connection.execute(
                    text(
                        f"ALTER TABLE exercises ADD COLUMN {column_name} {column_type}"
                    )
                )


async def close_db() -> None:
    await engine.dispose()
