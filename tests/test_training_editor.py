import unittest
from datetime import date, time
from unittest.mock import patch

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base
from database.models import Exercise, MuscleGroup, User
from database.repositories import (
    create_training_day,
    generate_workout_session,
    get_training_day,
    switch_workout_exercise,
)
from database.training_editor import (
    active_links,
    change_day_sets,
    set_day_exercise,
    toggle_day_alternative,
)
from handlers.training_editor import editor_screen
from database import session as db_session


class TrainingEditorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.session.add_all(
            [User(id=1, first_name="Test"), User(id=2, first_name="Other")]
        )
        await self.session.flush()
        self.session.add_all(
            [
                MuscleGroup(id=1, user_id=1, name="Спина"),
                MuscleGroup(id=2, user_id=1, name="Ноги"),
                MuscleGroup(id=3, user_id=2, name="Чужие"),
            ]
        )
        await self.session.flush()
        self.session.add_all(
            [
                Exercise(
                    id=1, user_id=1, muscle_group_id=1, name="Тяга", default_sets=3
                ),
                Exercise(
                    id=2,
                    user_id=1,
                    muscle_group_id=1,
                    name="Подтягивания",
                    default_sets=2,
                ),
                Exercise(
                    id=3, user_id=1, muscle_group_id=2, name="Присед", default_sets=3
                ),
                Exercise(id=4, user_id=2, muscle_group_id=3, name="Чужое"),
            ]
        )
        await self.session.commit()
        self.day = await create_training_day(
            self.session, 1, "План", 127, time(10), [(1, [1])], {}
        )
        self.day_id = self.day.id

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_add_remove_readd_and_group_counts(self):
        day = await set_day_exercise(self.session, 1, self.day_id, 3, True)
        self.assertEqual({link.exercise_id for link in active_links(day)}, {1, 3})
        self.assertEqual(
            {g.muscle_group_id: g.exercise_count for g in day.muscle_groups},
            {1: 1, 2: 1},
        )
        day = await set_day_exercise(self.session, 1, self.day_id, 1, False)
        self.assertEqual([link.exercise_id for link in active_links(day)], [3])
        day = await set_day_exercise(self.session, 1, self.day_id, 1, True)
        self.assertEqual(len(day.exercises), 2)
        self.assertEqual(len(active_links(day)), 2)

    async def test_cannot_remove_last_exercise(self):
        with self.assertRaises(ValueError):
            await set_day_exercise(self.session, 1, self.day_id, 1, False)

    async def test_sets_are_specific_to_plan_and_used_for_replacements(self):
        await change_day_sets(self.session, 1, self.day_id, 1, 1)
        day = await toggle_day_alternative(self.session, 1, self.day_id, 1, 2)
        workout = await generate_workout_session(self.session, day, date(2026, 6, 2))
        self.assertEqual(workout.exercises[0].sets_total, 4)
        self.assertEqual(len(workout.exercises[0].sets), 4)
        switched = await switch_workout_exercise(
            self.session, 1, workout.exercises[0].id
        )
        self.assertEqual(switched.exercises[0].exercise_id, 2)
        self.assertEqual(switched.exercises[0].sets_total, 4)
        self.assertEqual(len(switched.exercises[0].sets), 4)
        exercise = await self.session.get(Exercise, 1)
        self.assertEqual(exercise.default_sets, 3)

    async def test_alternative_toggle_and_validation(self):
        day = await toggle_day_alternative(self.session, 1, self.day_id, 1, 2)
        self.assertEqual([a.exercise_id for a in day.exercises[0].alternatives], [2])
        day = await toggle_day_alternative(self.session, 1, self.day_id, 1, 2)
        self.assertEqual(day.exercises[0].alternatives, [])
        for alternative in (1, 3, 4):
            with self.assertRaises(ValueError):
                await toggle_day_alternative(
                    self.session, 1, self.day_id, 1, alternative
                )

    async def test_ownership_and_set_limits(self):
        with self.assertRaises(ValueError):
            await set_day_exercise(self.session, 2, self.day_id, 4, True)
        with self.assertRaises(ValueError):
            await set_day_exercise(self.session, 1, self.day_id, 4, True)
        for _ in range(3):
            await change_day_sets(self.session, 1, self.day_id, 1, 1)
        with self.assertRaises(ValueError):
            await change_day_sets(self.session, 1, self.day_id, 1, 1)
        for _ in range(5):
            await change_day_sets(self.session, 1, self.day_id, 1, -1)
        with self.assertRaises(ValueError):
            await change_day_sets(self.session, 1, self.day_id, 1, -1)

    async def test_existing_session_and_history_preserved(self):
        workout = await generate_workout_session(
            self.session, self.day, date(2026, 6, 2)
        )
        old_id = workout.id
        workout.sent_at = workout.created_at
        workout.telegram_message_id = 42
        await self.session.commit()
        await set_day_exercise(self.session, 1, self.day_id, 3, True)
        day = await set_day_exercise(self.session, 1, self.day_id, 1, False)
        existing = await generate_workout_session(self.session, day, date(2026, 6, 2))
        self.assertEqual(existing.id, old_id)
        self.assertEqual([e.exercise_id for e in existing.exercises], [1])
        self.assertEqual(existing.telegram_message_id, 42)
        self.assertIsNotNone(existing.sent_at)
        next_workout = await generate_workout_session(
            self.session, day, date(2026, 6, 3)
        )
        self.assertEqual([e.exercise_id for e in next_workout.exercises], [3])

    async def test_selected_main_exercise_can_also_be_an_alternative(self):
        await set_day_exercise(self.session, 1, self.day_id, 2, True)
        day = await toggle_day_alternative(self.session, 1, self.day_id, 1, 2)
        workout = await generate_workout_session(self.session, day, date(2026, 6, 2))
        self.assertEqual([e.exercise_id for e in workout.exercises], [1, 2])

    async def test_all_editor_screens(self):
        for action, args in [
            ("open", ["0"]),
            ("add", ["0"]),
            ("exercise", ["1"]),
            ("alt", ["1", "0"]),
        ]:
            screen = await editor_screen(self.session, 1, self.day_id, action, args)
            self.assertIn("editday:", screen.html)

    async def test_init_db_does_not_reinsert_removed_exercises(self):
        await set_day_exercise(self.session, 1, self.day_id, 2, True)
        await set_day_exercise(self.session, 1, self.day_id, 1, False)
        with patch.object(db_session, "engine", self.engine):
            await db_session.init_db()
            await db_session.init_db()
        self.session.expire_all()
        day = await get_training_day(self.session, 1, self.day_id)
        self.assertEqual([link.exercise_id for link in active_links(day)], [2])
        self.assertEqual(len(day.exercises), 2)


class TrainingEditorMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_database_gets_columns_without_losing_links(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(
                    text("ALTER TABLE training_day_exercises DROP COLUMN sets_count")
                )
                await connection.execute(
                    text("ALTER TABLE training_day_exercises DROP COLUMN is_active")
                )
            with patch.object(db_session, "engine", engine):
                await db_session.init_db()
                await db_session.init_db()
            async with engine.begin() as connection:
                columns = await connection.run_sync(
                    lambda c: {
                        col["name"]
                        for col in inspect(c).get_columns("training_day_exercises")
                    }
                )
            self.assertTrue({"sets_count", "is_active"} <= columns)
        finally:
            await engine.dispose()


if __name__ == "__main__":
    unittest.main()
