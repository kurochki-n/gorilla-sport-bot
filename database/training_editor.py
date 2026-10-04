"""Редактирование шаблонов без удаления связей, на которые ссылается история."""

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    TrainingDay,
    TrainingDayExercise,
    TrainingDayExerciseAlternative,
    TrainingDayGroup,
)
from database.repositories import get_exercise, get_training_day


def active_links(day: TrainingDay) -> list[TrainingDayExercise]:
    return [
        link
        for link in day.exercises
        if link.is_active
        and link.exercise.is_active
        and link.exercise.muscle_group.is_active
    ]


async def editable_day(session: AsyncSession, user_id: int, day_id: int) -> TrainingDay:
    day = await get_training_day(session, user_id, day_id)
    if day is None or not day.is_active:
        raise ValueError("Тренировка недоступна")
    return day


async def _sync_groups(session: AsyncSession, day: TrainingDay) -> None:
    counts: dict[int, int] = {}
    for link in active_links(day):
        group_id = link.exercise.muscle_group_id
        counts[group_id] = counts.get(group_id, 0) + 1
    groups = {link.muscle_group_id: link for link in day.muscle_groups}
    for group_id, link in groups.items():
        link.exercise_count = counts.get(group_id, 0)
    for group_id, count in counts.items():
        if group_id not in groups:
            session.add(
                TrainingDayGroup(
                    training_day_id=day.id,
                    muscle_group_id=group_id,
                    exercise_count=count,
                    position=len(groups) + 1,
                )
            )


async def set_day_exercise(
    session: AsyncSession,
    user_id: int,
    day_id: int,
    exercise_id: int,
    enabled: bool,
) -> TrainingDay:
    day = await editable_day(session, user_id, day_id)
    exercise = await get_exercise(session, user_id, exercise_id)
    if (
        exercise is None
        or not exercise.is_active
        or not exercise.muscle_group.is_active
    ):
        raise ValueError("Упражнение недоступно")
    link = next(
        (item for item in day.exercises if item.exercise_id == exercise_id), None
    )
    if not enabled:
        if link is None or not link.is_active:
            raise ValueError("Упражнение уже убрано")
        if len(active_links(day)) <= 1:
            raise ValueError("В тренировке должно остаться хотя бы одно упражнение")
        link.is_active = False
    elif link is not None:
        link.is_active = True
    else:
        link = TrainingDayExercise(
            training_day_id=day.id,
            exercise=exercise,
            is_active=True,
            position=max((item.position for item in day.exercises), default=0) + 1,
        )
        day.exercises.append(link)
    await _sync_groups(session, day)
    await session.commit()
    return await editable_day(session, user_id, day_id)


async def change_day_sets(
    session: AsyncSession,
    user_id: int,
    day_id: int,
    exercise_id: int,
    delta: int,
) -> TrainingDay:
    day = await editable_day(session, user_id, day_id)
    link = next(
        (item for item in active_links(day) if item.exercise_id == exercise_id), None
    )
    if link is None:
        raise ValueError("Упражнение недоступно")
    count = (link.sets_count or link.exercise.default_sets) + delta
    if delta not in {-1, 1} or not 1 <= count <= 6:
        raise ValueError("Можно выбрать от 1 до 6 подходов")
    link.sets_count = count
    await session.commit()
    return await editable_day(session, user_id, day_id)


async def toggle_day_alternative(
    session: AsyncSession,
    user_id: int,
    day_id: int,
    source_id: int,
    alternative_id: int,
) -> TrainingDay:
    day = await editable_day(session, user_id, day_id)
    source = next(
        (item for item in active_links(day) if item.exercise_id == source_id), None
    )
    alternative = await get_exercise(session, user_id, alternative_id)
    if (
        source is None
        or alternative is None
        or not alternative.is_active
        or not alternative.muscle_group.is_active
        or alternative.id == source_id
        or alternative.muscle_group_id != source.exercise.muscle_group_id
    ):
        raise ValueError("Выбери другое активное упражнение той же группы мышц")
    existing = next(
        (item for item in source.alternatives if item.exercise_id == alternative_id),
        None,
    )
    if existing is not None:
        await session.delete(existing)
    else:
        session.add(
            TrainingDayExerciseAlternative(
                training_day_exercise_id=source.id,
                exercise_id=alternative_id,
                position=max((item.position for item in source.alternatives), default=0)
                + 1,
            )
        )
    await session.commit()
    return await editable_day(session, user_id, day_id)
