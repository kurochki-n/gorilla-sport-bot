import unittest
from datetime import date, time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base
from database.models import Exercise, MuscleGroup, User
from database.repositories import (
    adjust_workout_set_value,
    create_training_day,
    generate_workout_session,
    get_training_day,
    mark_workout_set_done,
    set_workout_set_note,
    switch_workout_exercise,
)
from database import session as db_session
from handlers.user_router import adjust_workout_value, complete_set, save_workout_note
from services.rich_messages import build_workout_exercise


class WorkoutNotesTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.session = async_sessionmaker(self.engine, expire_on_commit=False)()
        self.session.add(User(id=1, first_name="Test"))
        await self.session.flush()
        self.session.add(MuscleGroup(id=1, user_id=1, name="Спина"))
        await self.session.flush()
        self.session.add_all([
            Exercise(id=i, user_id=1, muscle_group_id=1, name=f"Тяга {i}",
                     default_sets=3, load_unit="кг")
            for i in (1, 2)
        ])
        await self.session.commit()
        self.day = await create_training_day(
            self.session, 1, "План", 127, time(10), [(1, [1])], {1: [2]}
        )
        self.workout = await generate_workout_session(self.session, self.day, date(2026, 6, 2))

    async def asyncTearDown(self):
        await self.session.close()
        await self.engine.dispose()

    async def test_notes_are_per_set_and_preserve_previous_snapshot(self):
        for workout_set, note in zip(self.workout.exercises[0].sets, ("decrease", "keep", "increase")):
            self.assertIsNone(await set_workout_set_note(self.session, 1, workout_set.id, note))
            await mark_workout_set_done(self.session, 1, workout_set.id)
            await set_workout_set_note(self.session, 1, workout_set.id, note)
        next_workout = await generate_workout_session(self.session, self.day, date(2026, 6, 3))
        self.assertEqual([s.previous_load_note for s in next_workout.exercises[0].sets],
                         ["decrease", "keep", "increase"])
        first = next_workout.exercises[0].sets[0]
        await mark_workout_set_done(self.session, 1, first.id)
        await set_workout_set_note(self.session, 1, first.id, "increase")
        self.assertEqual(first.previous_load_note, "decrease")
        self.assertEqual(first.load_note, "increase")
        self.assertIsNone(self.workout.exercises[0].sets[0].previous_load_note)
        html = build_workout_exercise(next_workout, 1).html
        self.assertIn("Оставить нагрузку", html)

    async def test_note_screen_before_next_set_and_after_last_set(self):
        for workout_set in self.workout.exercises[0].sets:
            workout, _, _, _ = await mark_workout_set_done(self.session, 1, workout_set.id)
            html = build_workout_exercise(workout, 1).html
            for note in ("decrease", "keep", "increase"):
                self.assertIn(f"workout:note:{workout_set.id}:{note}", html)
            self.assertNotIn("Завершить подход", html)
            workout = await set_workout_set_note(self.session, 1, workout_set.id, "keep")
            self.assertNotIn("workout:note:", build_workout_exercise(workout, 1).html)
        self.assertTrue(workout.is_completed)

    async def test_load_steps_limits_validation_and_ownership(self):
        first = self.workout.exercises[0].sets[0]
        html = build_workout_exercise(self.workout, 1).html
        for delta in (1, 2.5, 5, -1, -2.5, -5):
            self.assertIn(f"workout:value:{first.id}:load:{delta:+g}", html)
            before = first.load_value or 0
            await adjust_workout_set_value(self.session, 1, first.id, "load", delta)
            self.assertEqual(first.load_value, max(0, before + delta))
        self.assertIsNone(await adjust_workout_set_value(self.session, 2, first.id, "load", 5))
        self.assertIsNone(await adjust_workout_set_value(self.session, 1, first.id, "load", 100))
        self.assertIsNone(await adjust_workout_set_value(self.session, 1, first.id, "reps", 2.5))
        await mark_workout_set_done(self.session, 1, first.id)
        self.assertIsNone(await adjust_workout_set_value(self.session, 1, first.id, "load", 1))
        self.assertIsNone(await set_workout_set_note(self.session, 2, first.id, "keep"))
        self.assertIsNone(await set_workout_set_note(self.session, 1, first.id, "bad"))

    async def test_replacement_uses_its_own_notes(self):
        switched = await switch_workout_exercise(self.session, 1, self.workout.exercises[0].id)
        first = switched.exercises[0].sets[0]
        await mark_workout_set_done(self.session, 1, first.id)
        await set_workout_set_note(self.session, 1, first.id, "increase")
        self.day = await get_training_day(self.session, 1, switched.training_day_id)
        next_workout = await generate_workout_session(self.session, self.day, date(2026, 6, 3))
        self.assertIsNone(next_workout.exercises[0].sets[0].previous_load_note)
        switched = await switch_workout_exercise(self.session, 1, next_workout.exercises[0].id)
        self.assertEqual(switched.exercises[0].sets[0].previous_load_note, "increase")

    async def test_callback_flow_and_legacy_load_buttons(self):
        first = self.workout.exercises[0].sets[0]
        callback = SimpleNamespace(
            data=f"workout:value:{first.id}:load:+", from_user=SimpleNamespace(id=1),
            message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=1),
            bot=AsyncMock(), answer=AsyncMock(),
        )
        with patch("handlers.user_router.edit_rich", new_callable=AsyncMock) as edit:
            await adjust_workout_value(callback, self.session)
            self.assertEqual(first.load_value, 2.5)
            callback.data = f"workout:value:{first.id}:load:+1"
            await adjust_workout_value(callback, self.session)
            self.assertEqual(first.load_value, 3.5)
            callback.data = f"workout:set:{first.id}"
            await complete_set(callback, self.session)
            self.assertIn(f"workout:note:{first.id}:keep", edit.call_args.args[3].html)
            callback.data = f"workout:note:{first.id}:keep"
            await save_workout_note(callback, self.session)
            self.assertIn("Завершить подход", edit.call_args.args[3].html)
            self.assertEqual(first.load_note, "keep")

    async def test_migration_is_idempotent_and_preserves_history(self):
        first = self.workout.exercises[0].sets[0]
        await mark_workout_set_done(self.session, 1, first.id)
        async with self.engine.begin() as connection:
            await connection.execute(text("CREATE TABLE app_migrations (name VARCHAR(64) PRIMARY KEY)"))
            await connection.execute(text("INSERT INTO app_migrations VALUES ('reset_load_values_v1')"))
            await connection.execute(text("ALTER TABLE workout_sets DROP COLUMN previous_load_note"))
            await connection.execute(text("ALTER TABLE workout_sets DROP COLUMN load_note"))
        with patch.object(db_session, "engine", self.engine):
            await db_session.init_db()
            await db_session.init_db()
        async with self.engine.begin() as connection:
            columns = await connection.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("workout_sets")})
            self.assertTrue({"previous_load_note", "load_note"} <= columns)
            self.assertEqual(await connection.scalar(text("SELECT COUNT(*) FROM workout_sets WHERE is_done = 1")), 1)


if __name__ == "__main__":
    unittest.main()
