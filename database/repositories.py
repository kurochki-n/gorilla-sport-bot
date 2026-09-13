from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Exercise,
    ExerciseSetPreset,
    MuscleGroup,
    NotificationLog,
    TrainingDay,
    TrainingDayExercise,
    TrainingDayExerciseAlternative,
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
    description: str | None = None,
    media_file_id: str | None = None,
    media_type: str | None = None,
    load_unit: str = "кг",
) -> Exercise:
    exercise = Exercise(
        user_id=user_id,
        muscle_group_id=muscle_group_id,
        name=name,
        description=description,
        media_file_id=media_file_id,
        media_type=media_type,
        default_sets=default_sets,
        target_text=target_text,
        rest_seconds=rest_seconds,
        load_unit=load_unit,
    )
    session.add(exercise)
    await session.commit()
    await session.refresh(exercise)
    return exercise


async def update_exercise_field(
    session: AsyncSession, user_id: int, exercise_id: int, field: str, value
) -> Exercise | None:
    exercise = await get_exercise(session, user_id, exercise_id)
    if exercise is None or not exercise.is_active:
        return None
    if field not in {"name", "default_sets", "target_text", "rest_seconds", "load_unit"}:
        return None
    setattr(exercise, field, value)
    await session.commit()
    return exercise


async def update_exercise_content(
    session: AsyncSession,
    user_id: int,
    exercise_id: int,
    description: str | None,
    media_file_id: str | None,
    media_type: str | None,
) -> Exercise | None:
    exercise = await get_exercise(session, user_id, exercise_id)
    if exercise is None or not exercise.is_active:
        return None
    exercise.description = description
    exercise.media_file_id = media_file_id
    exercise.media_type = media_type
    await session.commit()
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
    group_exercises: list[tuple[int, list[int]]],
    alternatives: dict[int, list[int]],
) -> TrainingDay:
    training_day = TrainingDay(
        user_id=user_id,
        name=name,
        weekdays_mask=weekdays_mask,
        reminder_time=reminder_time,
    )
    session.add(training_day)
    await session.flush()
    selected_links: dict[int, TrainingDayExercise] = {}
    exercise_position = 1
    for group_position, (group_id, exercise_ids) in enumerate(
        group_exercises, start=1
    ):
        session.add(
            TrainingDayGroup(
                training_day_id=training_day.id,
                muscle_group_id=group_id,
                exercise_count=len(exercise_ids),
                position=group_position,
            )
        )
        for exercise_id in exercise_ids:
            selected_link = TrainingDayExercise(
                training_day_id=training_day.id,
                exercise_id=exercise_id,
                position=exercise_position,
            )
            session.add(selected_link)
            selected_links[exercise_id] = selected_link
            exercise_position += 1
    await session.flush()
    for source_exercise_id, alternative_ids in alternatives.items():
        selected_link = selected_links.get(source_exercise_id)
        if selected_link is None:
            continue
        for position, exercise_id in enumerate(alternative_ids, start=1):
            if exercise_id != source_exercise_id:
                session.add(
                    TrainingDayExerciseAlternative(
                        training_day_exercise_id=selected_link.id,
                        exercise_id=exercise_id,
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
            ),
            selectinload(TrainingDay.exercises)
            .selectinload(TrainingDayExercise.exercise)
            .selectinload(Exercise.muscle_group),
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
            ),
            selectinload(TrainingDay.exercises)
            .selectinload(TrainingDayExercise.exercise)
            .selectinload(Exercise.muscle_group),
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
            ),
            selectinload(TrainingDay.exercises)
            .selectinload(TrainingDayExercise.exercise)
            .selectinload(Exercise.muscle_group),
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
            selectinload(WorkoutSession.exercises)
            .selectinload(WorkoutExercise.training_day_exercise)
            .selectinload(TrainingDayExercise.alternatives),
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
            selectinload(WorkoutSession.exercises)
            .selectinload(WorkoutExercise.training_day_exercise)
            .selectinload(TrainingDayExercise.alternatives),
        )
        .where(
            WorkoutSession.user_id == user_id,
            WorkoutSession.training_day_id == training_day_id,
            WorkoutSession.scheduled_date == scheduled_date,
        )
    )


def _default_repetitions(target_text: str) -> int | None:
    match = re.search(r"\d+", target_text)
    return int(match.group()) if match else None


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
    alternative_ids = set(
        await session.scalars(
            select(TrainingDayExerciseAlternative.exercise_id)
            .join(TrainingDayExercise)
            .where(TrainingDayExercise.training_day_id == training_day.id)
        )
    )
    group_limit_rows = await session.execute(
        select(TrainingDayGroup.muscle_group_id, TrainingDayGroup.exercise_count).where(
            TrainingDayGroup.training_day_id == training_day.id
        )
    )
    group_limits = {
        muscle_group_id: exercise_count
        for muscle_group_id, exercise_count in group_limit_rows.all()
    }
    selected_by_group: dict[int, int] = {}
    selected_links: list[TrainingDayExercise] = []
    for link in training_day.exercises:
        exercise = link.exercise
        group_id = exercise.muscle_group_id
        if (
            exercise.id in alternative_ids
            or not exercise.is_active
            or not exercise.muscle_group.is_active
            or group_id not in group_limits
            or selected_by_group.get(group_id, 0) >= group_limits[group_id]
        ):
            continue
        selected_links.append(link)
        selected_by_group[group_id] = selected_by_group.get(group_id, 0) + 1
    selected_exercises = [link.exercise for link in selected_links]
    if not selected_exercises:
        return None
    if existing is not None:
        selected_link_ids = {link.id for link in selected_links}
        selected_exercise_ids = {exercise.id for exercise in selected_exercises}
        extras = [
            item
            for item in existing.exercises
            if (
                item.training_day_exercise_id not in selected_link_ids
                if item.training_day_exercise_id is not None
                else item.exercise_id not in selected_exercise_ids
            )
        ]
        if extras:
            for item in extras:
                await session.delete(item)
            await session.flush()
            for position, item in enumerate(
                (item for item in existing.exercises if item not in extras), start=1
            ):
                item.position = position
            existing_id = existing.id
            await session.commit()
            session.expire_all()
            existing = await get_workout_session(
                session, training_day.user_id, existing_id
            )
        if existing is not None and (
            existing.sets_done > 0 or len(existing.exercises) == len(selected_exercises)
        ):
            return existing
        if existing is not None:
            await session.delete(existing)
            await session.flush()

    workout = WorkoutSession(
        user_id=training_day.user_id,
        training_day_id=training_day.id,
        scheduled_date=scheduled_date,
    )
    session.add(workout)
    await session.flush()

    for position, exercise in enumerate(selected_exercises, start=1):
        workout_exercise = WorkoutExercise(
            session_id=workout.id,
            exercise_id=exercise.id,
            training_day_exercise_id=next(
                link.id for link in training_day.exercises if link.exercise_id == exercise.id
            ),
            muscle_group_id=exercise.muscle_group_id,
            exercise_name=exercise.name,
            muscle_group_name=exercise.muscle_group.name,
            sets_total=exercise.default_sets,
            target_text=exercise.target_text,
            rest_seconds=exercise.rest_seconds,
            load_unit=exercise.load_unit,
            position=position,
        )
        session.add(workout_exercise)
        await session.flush()
        for set_position in range(1, exercise.default_sets + 1):
            previous_set = await session.scalar(
                select(ExerciseSetPreset).where(
                    ExerciseSetPreset.user_id == training_day.user_id,
                    ExerciseSetPreset.exercise_id == exercise.id,
                    ExerciseSetPreset.position == set_position,
                )
            )
            session.add(
                WorkoutSet(
                    workout_exercise_id=workout_exercise.id,
                    position=set_position,
                    load_value=previous_set.load_value if previous_set else None,
                    repetitions=(
                        previous_set.repetitions
                        if previous_set and previous_set.repetitions is not None
                        else _default_repetitions(exercise.target_text)
                    ),
                )
            )

    await session.commit()
    return await get_workout_session(session, training_day.user_id, workout.id)


async def restart_workout_session(
    session: AsyncSession, user_id: int, workout_session_id: int
) -> WorkoutSession | None:
    workout = await get_workout_session(session, user_id, workout_session_id)
    if workout is None:
        return None
    training_day = await get_training_day(session, user_id, workout.training_day_id)
    if training_day is None or not training_day.is_active:
        return None
    scheduled_date = workout.scheduled_date
    await session.delete(workout)
    await session.flush()
    return await generate_workout_session(session, training_day, scheduled_date)


async def switch_workout_exercise(
    session: AsyncSession, user_id: int, workout_exercise_id: int
) -> WorkoutSession | None:
    workout_exercise = await session.scalar(
        select(WorkoutExercise)
        .options(
            selectinload(WorkoutExercise.session),
            selectinload(WorkoutExercise.sets),
            selectinload(WorkoutExercise.training_day_exercise)
            .selectinload(TrainingDayExercise.alternatives)
            .selectinload(TrainingDayExerciseAlternative.exercise)
            .selectinload(Exercise.muscle_group),
            selectinload(WorkoutExercise.training_day_exercise)
            .selectinload(TrainingDayExercise.exercise)
            .selectinload(Exercise.muscle_group),
        )
        .join(WorkoutSession)
        .where(WorkoutExercise.id == workout_exercise_id, WorkoutSession.user_id == user_id)
    )
    if (
        workout_exercise is None
        or workout_exercise.sets_done > 0
        or workout_exercise.training_day_exercise is None
    ):
        return None
    source = workout_exercise.training_day_exercise
    choices = [source.exercise] + [item.exercise for item in source.alternatives]
    if len(choices) < 2:
        return None
    current_index = next(
        (index for index, exercise in enumerate(choices) if exercise.id == workout_exercise.exercise_id),
        -1,
    )
    replacement = choices[(current_index + 1) % len(choices)]
    workout_exercise.exercise_id = replacement.id
    workout_exercise.muscle_group_id = replacement.muscle_group_id
    workout_exercise.exercise_name = replacement.name
    workout_exercise.muscle_group_name = replacement.muscle_group.name
    workout_exercise.sets_total = replacement.default_sets
    workout_exercise.target_text = replacement.target_text
    workout_exercise.rest_seconds = replacement.rest_seconds
    workout_exercise.load_unit = replacement.load_unit
    workout_exercise.sets_done = 0
    workout_exercise.completed_at = None
    workout_exercise.session.completed_at = None
    await session.execute(
        delete(WorkoutSet).where(WorkoutSet.workout_exercise_id == workout_exercise.id)
    )
    await session.flush()
    for position in range(1, replacement.default_sets + 1):
        session.add(WorkoutSet(workout_exercise_id=workout_exercise.id, position=position))
    session_id = workout_exercise.session_id
    await session.commit()
    session.expire_all()
    return await get_workout_session(session, user_id, session_id)


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


async def set_workout_exercise_unit(
    session: AsyncSession, user_id: int, workout_exercise_id: int, load_unit: str
) -> WorkoutSession | None:
    if load_unit not in {"кг", "км", "сек"}:
        return None
    workout_exercise = await session.scalar(
        select(WorkoutExercise).options(selectinload(WorkoutExercise.session))
        .join(WorkoutSession)
        .where(WorkoutExercise.id == workout_exercise_id, WorkoutSession.user_id == user_id)
    )
    if workout_exercise is None:
        return None
    exercise = await get_exercise(session, user_id, workout_exercise.exercise_id)
    if exercise is None:
        return None
    exercise.load_unit = load_unit
    workout_exercise.load_unit = load_unit
    session_id = workout_exercise.session_id
    await session.commit()
    return await get_workout_session(session, user_id, session_id)


async def adjust_workout_set_value(
    session: AsyncSession, user_id: int, set_id: int, field: str, delta: int
) -> WorkoutSession | None:
    workout_set = await session.scalar(
        select(WorkoutSet)
        .options(selectinload(WorkoutSet.workout_exercise).selectinload(WorkoutExercise.session))
        .join(WorkoutExercise).join(WorkoutSession)
        .where(WorkoutSet.id == set_id, WorkoutSession.user_id == user_id)
    )
    if workout_set is None or workout_set.is_done or field not in {"load", "reps"}:
        return None
    if field == "load":
        workout_set.load_value = max(0, (workout_set.load_value or 0) + delta * 2.5)
    else:
        workout_set.repetitions = max(0, (workout_set.repetitions or 0) + delta)
    session_id = workout_set.workout_exercise.session_id
    await session.commit()
    return await get_workout_session(session, user_id, session_id)


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
    preset = await session.scalar(
        select(ExerciseSetPreset).where(
            ExerciseSetPreset.user_id == user_id,
            ExerciseSetPreset.exercise_id == workout_exercise.exercise_id,
            ExerciseSetPreset.position == workout_set.position,
        )
    )
    if preset is None:
        preset = ExerciseSetPreset(
            user_id=user_id,
            exercise_id=workout_exercise.exercise_id,
            position=workout_set.position,
        )
        session.add(preset)
    preset.load_value = workout_set.load_value
    preset.repetitions = workout_set.repetitions
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
