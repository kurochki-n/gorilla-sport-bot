from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Exercise,
    MuscleGroup,
    NotificationLog,
    RotationEntry,
    TrainingDay,
    TrainingDayGroup,
    User,
    WorkoutExercise,
    WorkoutSession,
    WorkoutSet,
)


async def upsert_user(
    session: AsyncSession,
    user_id: int,
    first_name: str,
    last_name: str | None,
    username: str | None,
    default_timezone: str,
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        user = User(
            id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            timezone=default_timezone,
        )
        session.add(user)
    else:
        user.first_name = first_name
        user.last_name = last_name
        user.username = username
    await session.commit()
    return user


async def create_muscle_group(
    session: AsyncSession, user_id: int, name: str
) -> MuscleGroup:
    group = MuscleGroup(user_id=user_id, name=name)
    session.add(group)
    await session.commit()
    await session.refresh(group)
    return group


async def get_active_muscle_groups(
    session: AsyncSession, user_id: int
) -> list[MuscleGroup]:
    result = await session.scalars(
        select(MuscleGroup)
        .options(selectinload(MuscleGroup.exercises))
        .where(MuscleGroup.user_id == user_id, MuscleGroup.is_active.is_(True))
        .order_by(MuscleGroup.id)
    )
    return list(result.unique())


async def get_muscle_group(
    session: AsyncSession, user_id: int, group_id: int
) -> MuscleGroup | None:
    return await session.scalar(
        select(MuscleGroup)
        .options(selectinload(MuscleGroup.exercises))
        .where(MuscleGroup.id == group_id, MuscleGroup.user_id == user_id)
    )


async def deactivate_muscle_group(
    session: AsyncSession, user_id: int, group_id: int
) -> MuscleGroup | None:
    group = await get_muscle_group(session, user_id, group_id)
    if group is None or not group.is_active:
        return None
    group.is_active = False
    for exercise in group.exercises:
        exercise.is_active = False
    await session.execute(
        delete(TrainingDayGroup).where(TrainingDayGroup.muscle_group_id == group.id)
    )
    await session.commit()
    return group


async def create_exercise(
    session: AsyncSession,
    user_id: int,
    muscle_group_id: int,
    name: str,
    default_sets: int,
    target_text: str,
    rest_seconds: int,
) -> Exercise:
    exercise = Exercise(
        user_id=user_id,
        muscle_group_id=muscle_group_id,
        name=name,
        default_sets=default_sets,
        target_text=target_text,
        rest_seconds=rest_seconds,
    )
    session.add(exercise)
    await session.commit()
    await session.refresh(exercise)
    return exercise


async def get_active_exercises(
    session: AsyncSession,
    user_id: int,
    muscle_group_id: int | None = None,
) -> list[Exercise]:
    statement = (
        select(Exercise)
        .options(selectinload(Exercise.muscle_group))
        .where(Exercise.user_id == user_id, Exercise.is_active.is_(True))
        .order_by(Exercise.muscle_group_id, Exercise.id)
    )
    if muscle_group_id is not None:
        statement = statement.where(Exercise.muscle_group_id == muscle_group_id)
    result = await session.scalars(statement)
    return list(result.unique())


async def get_exercise(
    session: AsyncSession, user_id: int, exercise_id: int
) -> Exercise | None:
    return await session.scalar(
        select(Exercise)
        .options(selectinload(Exercise.muscle_group))
        .where(Exercise.id == exercise_id, Exercise.user_id == user_id)
    )


async def deactivate_exercise(
    session: AsyncSession, user_id: int, exercise_id: int
) -> Exercise | None:
    exercise = await get_exercise(session, user_id, exercise_id)
    if exercise is None or not exercise.is_active:
        return None
    exercise.is_active = False
    await session.commit()
    return exercise


async def create_training_day(
    session: AsyncSession,
    user_id: int,
    name: str,
    weekdays_mask: int,
    reminder_time,
    group_counts: list[tuple[int, int]],
) -> TrainingDay:
    training_day = TrainingDay(
        user_id=user_id,
        name=name,
        weekdays_mask=weekdays_mask,
        reminder_time=reminder_time,
    )
    session.add(training_day)
    await session.flush()
    for position, (group_id, count) in enumerate(group_counts, start=1):
        session.add(
            TrainingDayGroup(
                training_day_id=training_day.id,
                muscle_group_id=group_id,
                exercise_count=count,
                position=position,
            )
        )
    await session.commit()
    return await get_training_day(session, user_id, training_day.id)


async def get_active_training_days(
    session: AsyncSession, user_id: int
) -> list[TrainingDay]:
    result = await session.scalars(
        select(TrainingDay)
        .options(
            selectinload(TrainingDay.muscle_groups).selectinload(
                TrainingDayGroup.muscle_group
            )
        )
        .where(TrainingDay.user_id == user_id, TrainingDay.is_active.is_(True))
        .order_by(TrainingDay.id)
    )
    return list(result.unique())


async def get_all_training_days(
    session: AsyncSession, user_id: int
) -> list[TrainingDay]:
    result = await session.scalars(
        select(TrainingDay)
        .options(
            selectinload(TrainingDay.muscle_groups).selectinload(
                TrainingDayGroup.muscle_group
            )
        )
        .where(TrainingDay.user_id == user_id)
        .order_by(TrainingDay.id)
    )
    return list(result.unique())


async def get_training_day(
    session: AsyncSession, user_id: int, training_day_id: int
) -> TrainingDay | None:
    return await session.scalar(
        select(TrainingDay)
        .options(
            selectinload(TrainingDay.muscle_groups).selectinload(
                TrainingDayGroup.muscle_group
            )
        )
        .where(TrainingDay.id == training_day_id, TrainingDay.user_id == user_id)
    )


async def deactivate_training_day(
    session: AsyncSession,
    user_id: int,
    training_day_id: int,
    inactive_from: date,
) -> TrainingDay | None:
    training_day = await get_training_day(session, user_id, training_day_id)
    if training_day is None or not training_day.is_active:
        return None
    training_day.is_active = False

    today_session = await session.scalar(
        select(WorkoutSession)
        .options(selectinload(WorkoutSession.exercises))
        .where(
            WorkoutSession.training_day_id == training_day.id,
            WorkoutSession.scheduled_date == inactive_from,
        )
    )
    if today_session is not None and today_session.sets_done > 0:
        training_day.inactive_from = inactive_from + timedelta(days=1)
    else:
        training_day.inactive_from = inactive_from
        if today_session is not None:
            await session.delete(today_session)
    await session.commit()
    return training_day


async def _last_used_dates(
    session: AsyncSession,
    exercise_ids: list[int],
) -> dict[int, date]:
    if not exercise_ids:
        return {}
    rows = await session.execute(
        select(WorkoutExercise.exercise_id, func.max(WorkoutSession.scheduled_date))
        .join(WorkoutSession, WorkoutSession.id == WorkoutExercise.session_id)
        .where(WorkoutExercise.exercise_id.in_(exercise_ids))
        .group_by(WorkoutExercise.exercise_id)
    )
    return {
        exercise_id: used_date
        for exercise_id, used_date in rows.all()
        if used_date is not None
    }


async def _create_rotation_round(
    session: AsyncSession,
    muscle_group_id: int,
    exercises: list[Exercise],
    week_start: date,
    avoid_ids: set[int] | None = None,
) -> None:
    avoid_ids = avoid_ids or set()
    max_round = await session.scalar(
        select(func.max(RotationEntry.round_no)).where(
            RotationEntry.muscle_group_id == muscle_group_id,
            RotationEntry.week_start == week_start,
        )
    )
    round_no = int(max_round or 0) + 1

    ids = [exercise.id for exercise in exercises]
    last_used = await _last_used_dates(session, ids)
    random.SystemRandom().shuffle(ids)
    ids.sort(
        key=lambda exercise_id: (
            exercise_id in avoid_ids,
            last_used.get(exercise_id, date.min),
        )
    )
    for position, exercise_id in enumerate(ids, start=1):
        session.add(
            RotationEntry(
                muscle_group_id=muscle_group_id,
                exercise_id=exercise_id,
                week_start=week_start,
                round_no=round_no,
                position=position,
            )
        )
    await session.flush()


async def select_rotated_exercises(
    session: AsyncSession,
    user_id: int,
    muscle_group_id: int,
    count: int,
    scheduled_date: date,
) -> list[Exercise]:
    exercises = await get_active_exercises(session, user_id, muscle_group_id)
    if not exercises:
        return []
    count = min(count, len(exercises))
    active_by_id = {exercise.id: exercise for exercise in exercises}
    week_start = scheduled_date - timedelta(days=scheduled_date.weekday())
    selected: list[Exercise] = []
    selected_ids: set[int] = set()

    while len(selected) < count:
        entries = list(
            await session.scalars(
                select(RotationEntry)
                .where(
                    RotationEntry.muscle_group_id == muscle_group_id,
                    RotationEntry.week_start == week_start,
                    RotationEntry.is_used.is_(False),
                    RotationEntry.exercise_id.in_(active_by_id.keys()),
                )
                .order_by(RotationEntry.round_no, RotationEntry.position)
            )
        )
        entries = [entry for entry in entries if entry.exercise_id not in selected_ids]
        if not entries:
            await _create_rotation_round(
                session,
                muscle_group_id,
                exercises,
                week_start,
                avoid_ids=selected_ids,
            )
            continue

        entry = entries[0]
        entry.is_used = True
        entry.used_at = datetime.now(timezone.utc)
        selected.append(active_by_id[entry.exercise_id])
        selected_ids.add(entry.exercise_id)
        await session.flush()

    return selected


async def get_workout_session(
    session: AsyncSession,
    user_id: int,
    workout_session_id: int,
) -> WorkoutSession | None:
    return await session.scalar(
        select(WorkoutSession)
        .options(
            selectinload(WorkoutSession.training_day),
            selectinload(WorkoutSession.exercises).selectinload(WorkoutExercise.sets),
        )
        .where(
            WorkoutSession.id == workout_session_id, WorkoutSession.user_id == user_id
        )
    )


async def get_session_for_training_day(
    session: AsyncSession,
    user_id: int,
    training_day_id: int,
    scheduled_date: date,
) -> WorkoutSession | None:
    return await session.scalar(
        select(WorkoutSession)
        .options(
            selectinload(WorkoutSession.training_day),
            selectinload(WorkoutSession.exercises).selectinload(WorkoutExercise.sets),
        )
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.training_day_id == training_day_id,
            WorkoutSession.scheduled_date == scheduled_date,
        )
    )


async def generate_workout_session(
    session: AsyncSession,
    training_day: TrainingDay,
    scheduled_date: date,
) -> WorkoutSession | None:
    existing = await get_session_for_training_day(
        session,
        training_day.user_id,
        training_day.id,
        scheduled_date,
    )
    if existing is not None:
        return existing

    selections: list[tuple[TrainingDayGroup, list[Exercise]]] = []
    for link in sorted(training_day.muscle_groups, key=lambda item: item.position):
        if not link.muscle_group.is_active:
            continue
        picked = await select_rotated_exercises(
            session,
            training_day.user_id,
            link.muscle_group_id,
            link.exercise_count,
            scheduled_date,
        )
        if picked:
            selections.append((link, picked))

    if not selections:
        await session.rollback()
        return None

    workout = WorkoutSession(
        user_id=training_day.user_id,
        training_day_id=training_day.id,
        scheduled_date=scheduled_date,
    )
    session.add(workout)
    await session.flush()

    position = 1
    for link, picked in selections:
        for exercise in picked:
            workout_exercise = WorkoutExercise(
                session_id=workout.id,
                exercise_id=exercise.id,
                muscle_group_id=exercise.muscle_group_id,
                exercise_name=exercise.name,
                muscle_group_name=link.muscle_group.name,
                sets_total=exercise.default_sets,
                target_text=exercise.target_text,
                rest_seconds=exercise.rest_seconds,
                position=position,
            )
            session.add(workout_exercise)
            await session.flush()
            for set_position in range(1, exercise.default_sets + 1):
                session.add(
                    WorkoutSet(
                        workout_exercise_id=workout_exercise.id, position=set_position
                    )
                )
            position += 1

    await session.commit()
    return await get_workout_session(session, training_day.user_id, workout.id)


async def get_sessions_for_day(
    session: AsyncSession, user_id: int, day: date
) -> list[WorkoutSession]:
    result = await session.scalars(
        select(WorkoutSession)
        .options(
            selectinload(WorkoutSession.training_day),
            selectinload(WorkoutSession.exercises).selectinload(WorkoutExercise.sets),
        )
        .where(WorkoutSession.user_id == user_id, WorkoutSession.scheduled_date == day)
        .order_by(WorkoutSession.id)
    )
    return list(result.unique())


async def mark_workout_set_done(
    session: AsyncSession,
    user_id: int,
    set_id: int,
) -> tuple[WorkoutSession | None, WorkoutExercise | None, bool, bool]:
    workout_set = await session.scalar(
        select(WorkoutSet)
        .options(
            selectinload(WorkoutSet.workout_exercise)
            .selectinload(WorkoutExercise.session)
            .selectinload(WorkoutSession.training_day)
        )
        .join(WorkoutExercise)
        .join(WorkoutSession)
        .where(WorkoutSet.id == set_id, WorkoutSession.user_id == user_id)
    )
    if workout_set is None:
        return None, None, False, False
    workout_exercise = workout_set.workout_exercise
    workout = workout_exercise.session
    if workout_set.is_done:
        loaded = await get_workout_session(session, user_id, workout.id)
        exercise = (
            next(
                (item for item in loaded.exercises if item.id == workout_exercise.id),
                None,
            )
            if loaded
            else None
        )
        return loaded, exercise, False, False

    workout_set.is_done = True
    workout_set.completed_at = datetime.now(timezone.utc)
    await session.flush()

    exercise_done_count = await session.scalar(
        select(func.count(WorkoutSet.id)).where(
            WorkoutSet.workout_exercise_id == workout_exercise.id,
            WorkoutSet.is_done.is_(True),
        )
    )
    workout_exercise.sets_done = int(exercise_done_count or 0)
    just_exercise_completed = (
        workout_exercise.sets_done >= workout_exercise.sets_total
        and workout_exercise.completed_at is None
    )
    if just_exercise_completed:
        workout_exercise.completed_at = datetime.now(timezone.utc)

    session_set_totals = await session.execute(
        select(
            func.sum(WorkoutExercise.sets_total), func.sum(WorkoutExercise.sets_done)
        ).where(WorkoutExercise.session_id == workout.id)
    )
    total_sets, done_sets = session_set_totals.one()
    just_session_completed = (
        int(done_sets or 0) >= int(total_sets or 0) and workout.completed_at is None
    )
    if just_session_completed:
        workout.completed_at = datetime.now(timezone.utc)

    await session.commit()
    loaded = await get_workout_session(session, user_id, workout.id)
    exercise = (
        next(
            (item for item in loaded.exercises if item.id == workout_exercise.id), None
        )
        if loaded
        else None
    )
    return loaded, exercise, just_exercise_completed, just_session_completed


async def notification_was_sent(
    session: AsyncSession, workout_session_id: int, kind: str
) -> bool:
    notification_id = await session.scalar(
        select(NotificationLog.id).where(
            NotificationLog.session_id == workout_session_id,
            NotificationLog.kind == kind,
        )
    )
    return notification_id is not None


async def log_notification(
    session: AsyncSession, workout_session_id: int, kind: str
) -> None:
    session.add(
        NotificationLog(
            session_id=workout_session_id,
            kind=kind,
            sent_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()


async def reset_statistics(session: AsyncSession, user_id: int) -> int:
    """Delete a user's workout history while preserving their workout setup."""
    session_ids = select(WorkoutSession.id).where(WorkoutSession.user_id == user_id)
    workout_exercise_ids = select(WorkoutExercise.id).where(
        WorkoutExercise.session_id.in_(session_ids)
    )

    await session.execute(
        delete(NotificationLog).where(NotificationLog.session_id.in_(session_ids))
    )
    await session.execute(
        delete(WorkoutSet).where(
            WorkoutSet.workout_exercise_id.in_(workout_exercise_ids)
        )
    )
    await session.execute(
        delete(WorkoutExercise).where(WorkoutExercise.session_id.in_(session_ids))
    )
    result = await session.execute(
        delete(WorkoutSession).where(WorkoutSession.user_id == user_id)
    )
    await session.commit()
    return int(result.rowcount or 0)
