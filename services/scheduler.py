import asyncio
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config_reader import get_settings
from database.models import (
    Exercise,
    TrainingDay,
    TrainingDayExercise,
    TrainingDayGroup,
    User,
    WorkoutSession,
)
from database.repositories import generate_workout_session
from database.session import SessionFactory
from services.rich_messages import build_workout_overview, send_rich
from services.workouts import streaks

logger = logging.getLogger(__name__)


async def scheduler_loop(bot: Bot) -> None:
    settings = get_settings()
    while True:
        try:
            await tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(settings.scheduler_interval_seconds)


async def tick(bot: Bot) -> None:
    async with SessionFactory() as session:
        users = list(await session.scalars(select(User)))
        for user in users:
            try:
                zone = ZoneInfo(user.timezone)
            except ZoneInfoNotFoundError:
                zone = ZoneInfo(get_settings().default_timezone)

            local_now = datetime.now(timezone.utc).astimezone(zone)
            today = local_now.date()
            # Не больше одного сообщения за локальный день, в том числе после
            # перезапуска бота или получения тренировки вручную.
            sent_workout_id = await session.scalar(
                select(WorkoutSession.id).where(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.scheduled_date == today,
                    WorkoutSession.sent_at.is_not(None),
                ).limit(1)
            )
            if sent_workout_id is not None:
                continue

            training_days = list(
                (
                    await session.scalars(
                        select(TrainingDay)
                        .options(
                            selectinload(TrainingDay.muscle_groups).selectinload(
                                TrainingDayGroup.muscle_group
                            ),
                            selectinload(TrainingDay.exercises)
                            .selectinload(TrainingDayExercise.exercise)
                            .selectinload(Exercise.muscle_group),
                        )
                        .where(
                            TrainingDay.user_id == user.id,
                            TrainingDay.is_active.is_(True),
                        )
                        .order_by(TrainingDay.reminder_time, TrainingDay.id)
                    )
                ).unique()
            )

            for training_day in training_days:
                if not training_day.is_scheduled_for(today):
                    continue
                due_at = datetime.combine(
                    today, training_day.reminder_time, tzinfo=zone
                )
                if local_now < due_at:
                    continue

                workout = await generate_workout_session(session, training_day, today)
                if workout is None or workout.is_completed or workout.sets_done > 0:
                    continue

                current_streak, _ = await streaks(session, user.id, today)
                sent = await send_rich(
                    bot, user.id, build_workout_overview(workout, current_streak)
                )
                workout.telegram_message_id = sent.message_id
                workout.sent_at = datetime.now(timezone.utc)
                await session.commit()
                break
