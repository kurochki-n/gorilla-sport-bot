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
        added_load_unit = "load_unit" not in exercise_columns
        if added_load_unit:
            await connection.execute(
                text("ALTER TABLE exercises ADD COLUMN load_unit VARCHAR(8) DEFAULT 'кг'")
            )
            await connection.execute(text("UPDATE workout_sets SET load_value = NULL, repetitions = NULL"))
        workout_exercise_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("workout_exercises")
            }
        )
        if "load_unit" not in workout_exercise_columns:
            await connection.execute(
                text("ALTER TABLE workout_exercises ADD COLUMN load_unit VARCHAR(8) DEFAULT 'кг'")
            )

        # Старые тренировочные дни хранили только количество упражнений.
        # Для них один раз закрепляем первые активные упражнения каждой группы.
        await connection.execute(
            text(
                """
                INSERT INTO training_day_exercises (training_day_id, exercise_id, position)
                SELECT training_day_id, exercise_id, group_position + group_order * 1000
                FROM (
                    SELECT
                        tdg.training_day_id,
                        exercise.id AS exercise_id,
                        tdg.position AS group_order,
                        ROW_NUMBER() OVER (
                            PARTITION BY tdg.training_day_id, tdg.muscle_group_id
                            ORDER BY exercise.id
                        ) AS group_position,
                        tdg.exercise_count
                    FROM training_day_groups AS tdg
                    JOIN exercises AS exercise
                        ON exercise.muscle_group_id = tdg.muscle_group_id
                        AND exercise.is_active = 1
                ) AS legacy
                WHERE group_position <= exercise_count
                  AND NOT EXISTS (
                    SELECT 1
                    FROM training_day_exercises AS selected
                    WHERE selected.training_day_id = legacy.training_day_id
                      AND selected.exercise_id = legacy.exercise_id
                )
                """
            )
        )
        await connection.execute(text("DROP TABLE IF EXISTS rotation_entries"))

        workout_exercise_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("workout_exercises")
            }
        )
        if "training_day_exercise_id" not in workout_exercise_columns:
            await connection.execute(
                text(
                    "ALTER TABLE workout_exercises "
                    "ADD COLUMN training_day_exercise_id INTEGER"
                )
            )

        workout_set_columns = await connection.run_sync(
            lambda sync_connection: {
                column["name"]
                for column in inspect(sync_connection).get_columns("workout_sets")
            }
        )
        for column_name, column_type in {
            "load_value": "FLOAT",
            "repetitions": "INTEGER",
        }.items():
            if column_name not in workout_set_columns:
                await connection.execute(
                    text(f"ALTER TABLE workout_sets ADD COLUMN {column_name} {column_type}")
                )


async def close_db() -> None:
    await engine.dispose()
