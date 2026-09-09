import asyncio
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from config_reader import get_settings
from database.models import TrainingDay, TrainingDayGroup, User
from database.repositories import (
    generate_workout_session,
    log_notification,
    notification_was_sent,
)
from database.session import SessionFactory
from services.rich_messages import (
    build_motivation_message,
    build_workout_dashboard,
    send_rich,
)
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
            training_days = list(
                (
                    await session.scalars(
                        select(TrainingDay)
                        .options(
                            selectinload(TrainingDay.muscle_groups).selectinload(
                                TrainingDayGroup.muscle_group
                            )
                        )
                        .where(
                            TrainingDay.user_id == user.id,
                            TrainingDay.is_active.is_(True),
                        )
                        .order_by(TrainingDay.id)
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
                if workout is None:
                    continue

                current_streak, _ = await streaks(session, user.id, today)
                if workout.sent_at is None:
                    sent = await send_rich(
                        bot, user.id, build_workout_dashboard(workout, current_streak)
                    )
                    workout.telegram_message_id = sent.message_id
                    workout.sent_at = datetime.now(timezone.utc)
                    await session.commit()

                if workout.is_completed:
                    continue

                total = workout.sets_total
                done = workout.sets_done
                remaining = max(total - done, 0)
                percent = round(done / total * 100) if total else 0

                # Один контекстный нудж спустя 3 часа после запланированного старта.
                if local_now >= due_at + timedelta(
                    hours=3
                ) and not await notification_was_sent(session, workout.id, "progress"):
                    if done == 0:
                        title = "Пора начать тренировку"
                        body = f"Сегодня {training_day.name}. Начни хотя бы с первого подхода — всего в плане {total}."
                    elif percent < 50:
                        title = "Продолжай без спешки"
                        body = f"Выполнено {done}/{total} подходов. Осталось {remaining}; тренировка уже начата, главное — не бросать на середине."
                    elif percent < 80:
                        title = "Большая часть уже сделана"
                        body = f"Прогресс {percent}%. Осталось {remaining} подходов — до закрытой тренировки заметно ближе, чем до начала."
                    else:
                        title = "Финиш рядом"
                        body = f"Уже {percent}% тренировки готово. Осталось всего {remaining} подходов."
                    await send_rich(
                        bot,
                        user.id,
                        build_motivation_message(title, body, current_streak),
                    )
                    await log_notification(session, workout.id, "progress")

                # Вечером отдельно предупреждаем о серии, но только после наступления времени тренировки.
                if local_now.hour >= 21 and not await notification_was_sent(
                    session, workout.id, "streak_risk"
                ):
                    current_streak, _ = await streaks(session, user.id, today)
                    if current_streak > 0:
                        title = "Серия ещё сохраняется"
                        body = f"Осталось {remaining} подходов. Закрой сегодняшний план, чтобы сохранить серию тренировочных дней."
                    else:
                        title = "Закрой тренировочный день"
                        body = f"Осталось {remaining} подходов. Заверши тренировку сегодня и начни новую серию без пропусков."
                    await send_rich(
                        bot,
                        user.id,
                        build_motivation_message(title, body, current_streak),
                    )
                    await log_notification(session, workout.id, "streak_risk")
