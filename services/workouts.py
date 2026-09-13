from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Exercise,
    ExerciseSetPreset,
    TrainingDay,
    WorkoutExercise,
    WorkoutSession,
    WorkoutSet,
)
from database.repositories import get_all_training_days, get_active_training_days


def _created_date(training_day: TrainingDay, fallback: date) -> date:
    return training_day.created_at.date() if training_day.created_at else fallback


def _planned_by_date(
    training_days: list[TrainingDay], through: date, start: date | None = None
) -> dict[date, list[int]]:
    planned: dict[date, list[int]] = defaultdict(list)
    for training_day in training_days:
        first = max(_created_date(training_day, through), start or date.min)
        last = through
        if training_day.inactive_from is not None:
            last = min(last, training_day.inactive_from - timedelta(days=1))
        if first > last:
            continue
        current = first
        while current <= last:
            if training_day.weekdays_mask & (1 << current.weekday()):
                planned[current].append(training_day.id)
            current += timedelta(days=1)
    return dict(planned)


async def _session_progress_by_date(
    session: AsyncSession,
    user_id: int,
    start: date,
    through: date,
) -> dict[date, dict[int, tuple[int, int]]]:
    rows = await session.execute(
        select(
            WorkoutSession.scheduled_date,
            WorkoutSession.training_day_id,
            func.coalesce(func.sum(WorkoutExercise.sets_total), 0),
            func.coalesce(func.sum(WorkoutExercise.sets_done), 0),
        )
        .outerjoin(WorkoutExercise, WorkoutExercise.session_id == WorkoutSession.id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.scheduled_date.between(start, through),
        )
        .group_by(WorkoutSession.id)
    )
    result: dict[date, dict[int, tuple[int, int]]] = defaultdict(dict)
    for day, training_day_id, total, done in rows.all():
        result[day][training_day_id] = (int(total or 0), int(done or 0))
    return dict(result)


async def _daily_statuses(
    session: AsyncSession, user_id: int, through: date
) -> list[tuple[date, bool]]:
    training_days = await get_all_training_days(session, user_id)
    if not training_days:
        return []
    earliest = min(_created_date(item, through) for item in training_days)
    planned = _planned_by_date(training_days, through, earliest)
    progress = await _session_progress_by_date(session, user_id, earliest, through)

    statuses: list[tuple[date, bool]] = []
    for day in sorted(planned):
        planned_ids = planned[day]
        day_sessions = progress.get(day, {})
        completed = bool(planned_ids) and all(
            training_day_id in day_sessions
            and day_sessions[training_day_id][0] > 0
            and day_sessions[training_day_id][1] >= day_sessions[training_day_id][0]
            for training_day_id in planned_ids
        )
        statuses.append((day, completed))
    return statuses


async def streaks(session: AsyncSession, user_id: int, today: date) -> tuple[int, int]:
    statuses = await _daily_statuses(session, user_id, today)
    if not statuses:
        return 0, 0

    current = 0
    for day, completed in reversed(statuses):
        if day == today and not completed:
            continue
        if completed:
            current += 1
        else:
            break

    best = 0
    run = 0
    for _, completed in statuses:
        if completed:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return current, best


async def stats(
    session: AsyncSession, user_id: int, today: date
) -> dict[str, int | float]:
    training_days = await get_all_training_days(session, user_id)
    if training_days:
        earliest = min(_created_date(item, today) for item in training_days)
        planned = _planned_by_date(training_days, today, earliest)
        planned_count = sum(len(ids) for ids in planned.values())
    else:
        planned_count = 0

    completed_workouts = int(
        await session.scalar(
            select(func.count(WorkoutSession.id)).where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.completed_at.is_not(None),
            )
        )
        or 0
    )
    sets_done = int(
        await session.scalar(
            select(func.count(WorkoutSet.id))
            .join(WorkoutExercise)
            .join(WorkoutSession)
            .where(WorkoutSession.user_id == user_id, WorkoutSet.is_done.is_(True))
        )
        or 0
    )
    exercise_instances = int(
        await session.scalar(
            select(func.count(WorkoutExercise.id))
            .join(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutExercise.completed_at.is_not(None),
            )
        )
        or 0
    )
    current, best = await streaks(session, user_id, today)
    completion = (
        round(completed_workouts / planned_count * 100, 1) if planned_count else 0.0
    )
    return {
        "planned_workouts": planned_count,
        "completed_workouts": completed_workouts,
        "sets_done": sets_done,
        "exercise_instances": exercise_instances,
        "completion": completion,
        "streak": current,
        "best_streak": best,
    }


async def exercise_statistics(
    session: AsyncSession, user_id: int, exercise_id: int
) -> dict | None:
    exercise = await session.scalar(
        select(Exercise).where(Exercise.id == exercise_id, Exercise.user_id == user_id)
    )
    if exercise is None:
        return None
    row = await session.execute(
        select(
            func.count(WorkoutSet.id),
            func.coalesce(func.sum(WorkoutSet.repetitions), 0),
            func.max(WorkoutSet.repetitions),
            func.max(WorkoutSet.load_value),
            func.max(WorkoutSession.scheduled_date),
        )
        .join(WorkoutExercise, WorkoutExercise.id == WorkoutSet.workout_exercise_id)
        .join(WorkoutSession, WorkoutSession.id == WorkoutExercise.session_id)
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutExercise.exercise_id == exercise_id,
            WorkoutSet.is_done.is_(True),
        )
    )
    sets_done, repetitions_total, repetitions_best, load_best, last_date = row.one()
    presets = list(
        await session.scalars(
            select(ExerciseSetPreset)
            .where(
                ExerciseSetPreset.user_id == user_id,
                ExerciseSetPreset.exercise_id == exercise_id,
            )
            .order_by(ExerciseSetPreset.position)
        )
    )
    return {
        "name": exercise.name,
        "unit": exercise.load_unit or "не задан",
        "sets_done": int(sets_done or 0),
        "repetitions_total": int(repetitions_total or 0),
        "repetitions_best": int(repetitions_best or 0),
        "load_best": load_best,
        "last_date": last_date,
        "presets": presets,
    }


async def calendar_data(session: AsyncSession, user_id: int, today: date) -> list[dict]:
    month_start = today.replace(day=1)
    if month_start.month == 12:
        next_month_start = date(month_start.year + 1, 1, 1)
    else:
        next_month_start = date(month_start.year, month_start.month + 1, 1)
    month_end = next_month_start - timedelta(days=1)
    grid_start = month_start - timedelta(days=month_start.weekday())
    grid_end = month_end + timedelta(days=6 - month_end.weekday())

    training_days = await get_all_training_days(session, user_id)
    planned = _planned_by_date(training_days, today, month_start)
    progress = await _session_progress_by_date(session, user_id, month_start, today)

    output: list[dict] = []
    day = grid_start
    while day <= grid_end:
        if day < month_start or day > month_end:
            output.append({"date": None, "status": "empty", "progress": 0})
            day += timedelta(days=1)
            continue

        planned_ids = planned.get(day, [])
        day_sessions = progress.get(day, {})
        if day > today:
            status = "future"
            percent = 0
        elif not planned_ids:
            status = "empty"
            percent = 0
        else:
            total_sets = sum(
                day_sessions.get(training_day_id, (0, 0))[0]
                for training_day_id in planned_ids
            )
            done_sets = sum(
                day_sessions.get(training_day_id, (0, 0))[1]
                for training_day_id in planned_ids
            )
            all_completed = all(
                training_day_id in day_sessions
                and day_sessions[training_day_id][0] > 0
                and day_sessions[training_day_id][1] >= day_sessions[training_day_id][0]
                for training_day_id in planned_ids
            )
            if all_completed:
                status = "done"
            elif done_sets > 0:
                status = "partial"
            else:
                status = "pending" if day == today else "missed"
            percent = round(done_sets / total_sets * 100) if total_sets else 0
        output.append({"date": day, "status": status, "progress": percent})
        day += timedelta(days=1)
    return output


async def scheduled_training_days(
    session: AsyncSession, user_id: int, day: date
) -> list[TrainingDay]:
    training_days = await get_active_training_days(session, user_id)
    return [item for item in training_days if item.is_scheduled_for(day)]
