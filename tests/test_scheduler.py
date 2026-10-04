import unittest
from datetime import datetime, time, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services import scheduler


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def run_tick(self, *, hour=12, scheduled=True, sent=False, workouts=None):
        now = datetime(2026, 6, 2, hour, tzinfo=timezone.utc)
        user = SimpleNamespace(id=1, timezone="UTC")
        days = [
            SimpleNamespace(
                id=i,
                reminder_time=time(10),
                is_scheduled_for=MagicMock(return_value=scheduled),
            )
            for i in (1, 2)
        ]
        if workouts is None:
            workouts = [
                SimpleNamespace(id=1, is_completed=False, sets_done=0, sent_at=None)
            ]
        session = AsyncMock()
        day_result = MagicMock()
        day_result.unique.return_value = days
        session.scalars.side_effect = [[user], day_result]
        session.scalar.return_value = 1 if sent else None
        factory = MagicMock()
        factory.return_value.__aenter__ = AsyncMock(return_value=session)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        with (
            patch.object(scheduler, "SessionFactory", factory),
            patch.object(scheduler, "datetime") as clock,
            patch.object(scheduler, "generate_workout_session", AsyncMock(side_effect=workouts)) as generate,
            patch.object(scheduler, "streaks", AsyncMock(return_value=(0, 0))),
            patch.object(scheduler, "build_workout_overview", return_value="overview"),
            patch.object(scheduler, "send_rich", AsyncMock(return_value=SimpleNamespace(message_id=42))) as send,
        ):
            clock.now.return_value = now
            clock.combine.side_effect = datetime.combine
            await scheduler.tick(MagicMock())
        return session, generate, send, workouts

    async def test_sends_only_one_message_for_multiple_training_days(self):
        session, generate, send, workouts = await self.run_tick()
        send.assert_awaited_once()
        generate.assert_awaited_once()
        session.commit.assert_awaited_once()
        self.assertEqual(workouts[0].telegram_message_id, 42)
        self.assertIsNotNone(workouts[0].sent_at)

    async def test_no_message_before_scheduled_time(self):
        _, generate, send, _ = await self.run_tick(hour=9)
        generate.assert_not_awaited()
        send.assert_not_awaited()

    async def test_no_message_on_rest_day(self):
        _, generate, send, _ = await self.run_tick(scheduled=False)
        generate.assert_not_awaited()
        send.assert_not_awaited()

    async def test_no_repeated_or_evening_notifications(self):
        for hour in (12, 15, 21, 23):
            with self.subTest(hour=hour):
                _, generate, send, _ = await self.run_tick(hour=hour, sent=True)
                generate.assert_not_awaited()
                send.assert_not_awaited()

    async def test_no_notification_for_started_or_completed_workouts(self):
        workouts = [
            SimpleNamespace(is_completed=False, sets_done=1),
            SimpleNamespace(is_completed=True, sets_done=10),
        ]
        _, _, send, _ = await self.run_tick(workouts=workouts)
        send.assert_not_awaited()

    async def test_empty_plan_does_not_block_valid_plan(self):
        workout = SimpleNamespace(id=2, is_completed=False, sets_done=0, sent_at=None)
        _, generate, send, _ = await self.run_tick(workouts=[None, workout])
        self.assertEqual(generate.await_count, 2)
        send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
