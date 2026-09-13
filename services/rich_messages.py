from __future__ import annotations

from collections import defaultdict
from html import escape

from aiogram import Bot
from aiogram.methods import EditMessageText, SendRichMessage
from aiogram.types import InputRichMessage

from database.models import Exercise, MuscleGroup, TrainingDay, WorkoutSession
from utils.dates import mask_to_text


def simple_rich(title: str, body_html: str, buttons_html: str = "") -> InputRichMessage:
    return InputRichMessage(html=f"<h3>{escape(title)}</h3>{body_html}{buttons_html}")


async def send_rich(
    bot: Bot, chat_id: int, rich_message: InputRichMessage, reply_markup=None
):
    return await bot(
        SendRichMessage(
            chat_id=chat_id, rich_message=rich_message, reply_markup=reply_markup
        )
    )


async def edit_rich(
    bot: Bot, chat_id: int, message_id: int, rich_message: InputRichMessage
):
    return await bot(
        EditMessageText(
            chat_id=chat_id, message_id=message_id, rich_message=rich_message
        )
    )


def build_weekdays_message(selected_mask: int = 0) -> InputRichMessage:
    names = [
        ("Пн", 0),
        ("Вт", 1),
        ("Ср", 2),
        ("Чт", 3),
        ("Пт", 4),
        ("Сб", 5),
        ("Вс", 6),
    ]
    buttons = []
    for label, index in names:
        selected = bool(selected_mask & (1 << index))
        style = "success" if selected else "primary"
        text = f"✓ {label}" if selected else label
        buttons.append(
            f'<tg-button type="callback_data" style="{style}" data="day:weekday:{index}">{text}</tg-button>'
        )
    return InputRichMessage(
        html=(
            "<h3>Дни тренировки</h3>"
            "<p>Выбери дни недели, когда этот шаблон должен появляться.</p>"
            f'<tg-button-row align="left">{"".join(buttons[:4])}</tg-button-row>'
            f'<tg-button-row align="left">{"".join(buttons[4:])}</tg-button-row>'
            '<tg-button-row><tg-button type="callback_data" data="day:weekday:all">Каждый день</tg-button>'
            '<tg-button type="callback_data" style="success" data="day:weekday:done">Готово</tg-button></tg-button-row>'
        )
    )


def build_groups_message(groups: list[MuscleGroup]) -> InputRichMessage:
    if not groups:
        return simple_rich(
            "Группы мышц",
            "<p>Пока нет ни одной группы мышц.</p><p>Сначала создай группу, например <b>Спина</b> или <b>Грудь</b>.</p>",
            '<tg-button-row><tg-button type="callback_data" style="primary" data="group:new">Добавить группу</tg-button></tg-button-row>',
        )

    blocks = ["<h3>Группы мышц</h3>"]
    for group in groups:
        active_count = sum(1 for exercise in group.exercises if exercise.is_active)
        blocks.append(
            "<table compact>"
            f'<tr><td><b>{escape(group.name)}</b></td><td align="right">{active_count} упр.</td></tr>'
            "</table>"
            f'<tg-button-row align="right"><tg-button type="callback_data" style="danger" data="group:delete:{group.id}">Удалить</tg-button></tg-button-row>'
        )
    blocks.append(
        '<tg-button-row><tg-button type="callback_data" style="primary" data="group:new">+ Добавить группу</tg-button></tg-button-row>'
    )
    return InputRichMessage(html="".join(blocks))


def build_group_delete_confirmation(group: MuscleGroup) -> InputRichMessage:
    active_count = sum(1 for exercise in group.exercises if exercise.is_active)
    return simple_rich(
        "Удалить группу мышц?",
        f"<p><b>{escape(group.name)}</b><br>Активных упражнений: {active_count}</p>"
        "<p>Упражнения этой группы тоже станут неактивными. История прошлых тренировок сохранится.</p>",
        f'<tg-button-row><tg-button type="callback_data" style="danger" data="group:confirm_delete:{group.id}">Да, удалить</tg-button>'
        '<tg-button type="callback_data" data="group:cancel_delete">Отмена</tg-button></tg-button-row>',
    )


def build_exercise_group_picker(groups: list[MuscleGroup]) -> InputRichMessage:
    rows = []
    for offset in range(0, len(groups), 2):
        buttons = [
            f'<tg-button type="callback_data" style="primary" data="exercise:group:{group.id}">{escape(group.name)}</tg-button>'
            for group in groups[offset : offset + 2]
        ]
        rows.append(f'<tg-button-row align="left">{"".join(buttons)}</tg-button-row>')
    return simple_rich(
        "Новое упражнение · 1/7",
        "<p>Для какой группы мышц добавить упражнение?</p>",
        "".join(rows),
    )


def build_exercises_message(exercises: list[Exercise]) -> InputRichMessage:
    if not exercises:
        return simple_rich(
            "Упражнения",
            "<p>Пока нет упражнений.</p>",
            '<tg-button-row><tg-button type="callback_data" style="primary" data="exercise:new">Добавить упражнение</tg-button></tg-button-row>',
        )

    grouped: dict[int, list[Exercise]] = defaultdict(list)
    for exercise in exercises:
        grouped[exercise.muscle_group_id].append(exercise)

    blocks = ["<h3>Упражнения</h3>"]
    for group_exercises in grouped.values():
        group = group_exercises[0].muscle_group
        blocks.append(f"<h4>{escape(group.name)}</h4>")
        for exercise in group_exercises:
            rest = f"{exercise.rest_seconds} сек отдыха"
            blocks.append(
                "<table compact>"
                f'<tr><td><b>{escape(exercise.name)}</b></td><td align="right">{exercise.default_sets} подх.</td></tr>'
                f'<tr><td>{escape(exercise.target_text)}</td><td align="right">{rest}</td></tr>'
                "</table>"
                f'<tg-button-row align="right"><tg-button type="callback_data" data="exercise:details:{exercise.id}">Посмотреть</tg-button>'
                f'<tg-button type="callback_data" style="danger" data="exercise:delete:{exercise.id}">Удалить</tg-button></tg-button-row>'
            )
    blocks.append(
        '<tg-button-row><tg-button type="callback_data" style="primary" data="exercise:new">+ Добавить упражнение</tg-button></tg-button-row>'
    )
    return InputRichMessage(html="".join(blocks))


def build_exercise_delete_confirmation(exercise: Exercise) -> InputRichMessage:
    return simple_rich(
        "Удалить упражнение?",
        f"<p><b>{escape(exercise.name)}</b><br>{escape(exercise.muscle_group.name)} · "
        f"{exercise.default_sets} × {escape(exercise.target_text)}</p>"
        "<p>Оно больше не попадёт в новые тренировки, но останется в истории.</p>",
        f'<tg-button-row><tg-button type="callback_data" style="danger" data="exercise:confirm_delete:{exercise.id}">Да, удалить</tg-button>'
        '<tg-button type="callback_data" data="exercise:cancel_delete">Отмена</tg-button></tg-button-row>',
    )


def build_day_groups_picker(
    groups: list[MuscleGroup], selected_ids: set[int]
) -> InputRichMessage:
    rows = []
    for offset in range(0, len(groups), 2):
        buttons = []
        for group in groups[offset : offset + 2]:
            selected = group.id in selected_ids
            style = "success" if selected else "primary"
            prefix = "✓ " if selected else ""
            buttons.append(
                f'<tg-button type="callback_data" style="{style}" data="day:group:{group.id}">{prefix}{escape(group.name)}</tg-button>'
            )
        rows.append(f'<tg-button-row align="left">{"".join(buttons)}</tg-button-row>')
    rows.append(
        '<tg-button-row><tg-button type="callback_data" style="success" data="day:group:done">Продолжить</tg-button></tg-button-row>'
    )
    return simple_rich(
        "Новый тренировочный день · группы",
        "<p>Выбери группы мышц. Для каждой дальше выберем упражнения.</p>",
        "".join(rows),
    )


def build_group_exercises_picker(
    group: MuscleGroup, selected_ids: set[int], index: int, total: int
) -> InputRichMessage:
    exercises = [exercise for exercise in group.exercises if exercise.is_active]
    rows = []
    for exercise in exercises:
        selected = exercise.id in selected_ids
        style = "success" if selected else "primary"
        prefix = "✓ " if selected else ""
        rows.append(
            f'<tg-button-row><tg-button type="callback_data" style="{style}" data="day:exercise:{exercise.id}">{prefix}{escape(exercise.name)}</tg-button></tg-button-row>'
        )
    rows.append(
        '<tg-button-row><tg-button type="callback_data" style="success" data="day:exercise:done">Продолжить</tg-button></tg-button-row>'
    )
    return simple_rich(
        f"{group.name} · {index}/{total}",
        f"<p>Выбери упражнения для группы <b>{escape(group.name)}</b>. Они будут повторяться в каждой тренировке.</p>",
        "".join(rows),
    )


def build_alternative_bases_picker(
    exercises: list[Exercise], selected_ids: set[int]
) -> InputRichMessage:
    rows = []
    for exercise in exercises:
        selected = exercise.id in selected_ids
        style = "success" if selected else "primary"
        prefix = "✓ " if selected else ""
        rows.append(
            f'<tg-button-row><tg-button type="callback_data" style="{style}" data="day:alternative_base:{exercise.id}">{prefix}{escape(exercise.name)}</tg-button></tg-button-row>'
        )
    rows.append(
        '<tg-button-row><tg-button type="callback_data" style="success" data="day:alternative_base:done">Продолжить</tg-button></tg-button-row>'
    )
    return simple_rich(
        "Альтернативные упражнения",
        "<p>Выбери упражнения, для которых хочешь добавить альтернативу. Этот шаг можно пропустить.</p>",
        "".join(rows),
    )


def build_alternatives_picker(
    base_exercise: Exercise,
    exercises: list[Exercise],
    selected_ids: set[int],
    index: int,
    total: int,
) -> InputRichMessage:
    rows = []
    for exercise in exercises:
        if exercise.id == base_exercise.id:
            continue
        selected = exercise.id in selected_ids
        style = "success" if selected else "primary"
        prefix = "✓ " if selected else ""
        rows.append(
            f'<tg-button-row><tg-button type="callback_data" style="{style}" data="day:alternative:{exercise.id}">{prefix}{escape(exercise.name)} · {escape(exercise.muscle_group.name)}</tg-button></tg-button-row>'
        )
    rows.append(
        '<tg-button-row><tg-button type="callback_data" style="success" data="day:alternative:done">Сохранить замены</tg-button></tg-button-row>'
    )
    return simple_rich(
        f"Замены · {index}/{total}",
        f"<p>Выбери альтернативы для <b>{escape(base_exercise.name)}</b>. Они будут переключаться по кругу во время тренировки.</p>",
        "".join(rows),
    )


def build_training_days_message(training_days: list[TrainingDay]) -> InputRichMessage:
    if not training_days:
        return simple_rich(
            "Тренировочные дни",
            "<p>Пока нет расписания.</p><p>Создай день после того, как добавишь группы мышц и упражнения.</p>",
            '<tg-button-row><tg-button type="callback_data" style="primary" data="day:new">Создать тренировочный день</tg-button></tg-button-row>',
        )

    blocks = ["<h3>Тренировочные дни</h3>"]
    for training_day in training_days:
        group_text = (
            ", ".join(
                f"{link.muscle_group.name} × {link.exercise_count}"
                for link in sorted(
                    training_day.muscle_groups, key=lambda item: item.position
                )
                if link.muscle_group.is_active
            )
            or "нет активных групп"
        )
        blocks.append(
            "<table compact>"
            f'<tr><td><b>{escape(training_day.name)}</b></td><td align="right">{training_day.reminder_time.strftime("%H:%M")}</td></tr>'
            f'<tr><td>{escape(mask_to_text(training_day.weekdays_mask))}</td><td align="right">{escape(group_text)}</td></tr>'
            "</table>"
            f'<tg-button-row align="right"><tg-button type="callback_data" style="success" data="day:start:{training_day.id}">Начать</tg-button>'
            f'<tg-button type="callback_data" style="danger" data="day:delete:{training_day.id}">Удалить</tg-button></tg-button-row>'
        )
    blocks.append(
        '<tg-button-row><tg-button type="callback_data" style="primary" data="day:new">+ Создать день</tg-button></tg-button-row>'
    )
    return InputRichMessage(html="".join(blocks))


def build_training_day_delete_confirmation(
    training_day: TrainingDay,
) -> InputRichMessage:
    return simple_rich(
        "Удалить тренировочный день?",
        f"<p><b>{escape(training_day.name)}</b><br>{escape(mask_to_text(training_day.weekdays_mask))} · "
        f"{training_day.reminder_time.strftime('%H:%M')}</p>"
        "<p>Будущие тренировки по этому шаблону больше не создаются. История сохранится.</p>",
        f'<tg-button-row><tg-button type="callback_data" style="danger" data="day:confirm_delete:{training_day.id}">Да, удалить</tg-button>'
        '<tg-button type="callback_data" data="day:cancel_delete">Отмена</tg-button></tg-button-row>',
    )


def _set_buttons(workout_session: WorkoutSession) -> str:
    blocks: list[str] = []
    current_group = None
    for item in sorted(
        workout_session.exercises, key=lambda exercise: exercise.position
    ):
        if item.muscle_group_name != current_group:
            current_group = item.muscle_group_name
            blocks.append(f"<h4>{escape(current_group)}</h4>")

        complete_mark = " ✅" if item.is_completed else ""
        blocks.append(
            f"<p><b>{item.position}. {escape(item.exercise_name)}{complete_mark}</b><br>"
            f"{item.sets_total} подхода × {escape(item.target_text)} · отдых {item.rest_seconds} сек</p>"
        )
        buttons = []
        for workout_set in sorted(item.sets, key=lambda set_item: set_item.position):
            if workout_set.is_done:
                buttons.append(
                    f'<tg-button type="disabled" style="success">✓ {workout_set.position}</tg-button>'
                )
            else:
                buttons.append(
                    f'<tg-button type="callback_data" style="primary" data="workout:set:{workout_set.id}">{workout_set.position}</tg-button>'
                )
        action_buttons = (
            f'<tg-button type="callback_data" data="exercise:details:{item.exercise_id}">Описание и медиа</tg-button>'
        )
        if item.training_day_exercise and item.training_day_exercise.alternatives:
            action_buttons += (
                f'<tg-button type="callback_data" data="workout:replace:{item.id}">Заменить</tg-button>'
            )
        blocks.append(f'<tg-button-row align="left">{action_buttons}</tg-button-row>')
        for offset in range(0, len(buttons), 6):
            blocks.append(
                f'<tg-button-row align="left">{"".join(buttons[offset : offset + 6])}</tg-button-row>'
            )
    return "".join(blocks)


def build_workout_overview(
    workout_session: WorkoutSession, streak: int = 0
) -> InputRichMessage:
    total = workout_session.sets_total
    exercise_count = len(workout_session.exercises)
    streak_text = f" · 🔥 <b>{streak}</b>" if streak else ""
    groups = ", ".join(
        dict.fromkeys(item.muscle_group_name for item in workout_session.exercises)
    )
    if workout_session.sets_done > 0:
        buttons = (
            f'<tg-button-row><tg-button type="callback_data" style="success" data="workout:begin:{workout_session.id}">Продолжить тренировку</tg-button>'
            f'<tg-button type="callback_data" data="workout:restart:{workout_session.id}">Начать заново</tg-button></tg-button-row>'
        )
        progress = f"<p>Уже отмечено: <b>{workout_session.sets_done}/{total}</b> подходов.</p>"
    else:
        buttons = (
            f'<tg-button-row><tg-button type="callback_data" style="success" data="workout:begin:{workout_session.id}">Начать тренировку</tg-button></tg-button-row>'
        )
        progress = ""
    return simple_rich(
        workout_session.training_day.name,
        f"<p><b>{exercise_count} упр. · {total} подходов</b>{streak_text}</p>"
        f"<p>{escape(groups)}</p>{progress}<p>Упражнения будут показаны по одному.</p>",
        buttons,
    )


def build_workout_exercise(
    workout_session: WorkoutSession, position: int, streak: int = 0
) -> InputRichMessage:
    exercises = sorted(workout_session.exercises, key=lambda item: item.position)
    item = next((exercise for exercise in exercises if exercise.position == position), None)
    if item is None:
        return build_workout_overview(workout_session, streak)
    streak_text = f" · 🔥 <b>{streak}</b>" if streak else ""
    complete_mark = " ✅" if item.is_completed else ""
    buttons = []
    for workout_set in sorted(item.sets, key=lambda set_item: set_item.position):
        if workout_set.is_done:
            buttons.append(
                f'<tg-button type="disabled" style="success">✓ {workout_set.position}</tg-button>'
            )
        else:
            buttons.append(
                f'<tg-button type="callback_data" style="primary" data="workout:set:{workout_set.id}">{workout_set.position}</tg-button>'
            )
    action_buttons = ""
    if (
        item.sets_done == 0
        and item.training_day_exercise
        and item.training_day_exercise.alternatives
    ):
        action_buttons += (
            f'<tg-button type="callback_data" data="workout:replace:{item.id}">Заменить</tg-button>'
        )
    action_buttons += (
        f'<tg-button type="callback_data" data="exercise:details:{item.exercise_id}">Описание и медиа</tg-button>'
    )
    previous = (
        f'<tg-button type="callback_data" data="workout:nav:{workout_session.id}:{position - 1}">←</tg-button>'
        if position > 1
        else '<tg-button type="disabled">←</tg-button>'
    )
    following = (
        f'<tg-button type="callback_data" data="workout:nav:{workout_session.id}:{position + 1}">→</tg-button>'
        if position < len(exercises)
        else '<tg-button type="disabled">→</tg-button>'
    )
    blocks = [
        f"<h3>{escape(workout_session.training_day.name)}</h3>",
        f"<p><b>{position}/{len(exercises)} · {escape(item.muscle_group_name)}</b>{streak_text}</p>",
        f"<p><b>{escape(item.exercise_name)}{complete_mark}</b></p>",
        f'<tg-button-row align="left">{action_buttons}</tg-button-row>',
        f"<p>{item.sets_total} подхода × {escape(item.target_text)} · отдых {item.rest_seconds} сек</p>",
    ]
    for offset in range(0, len(buttons), 6):
        blocks.append(
            f'<tg-button-row align="left">{"".join(buttons[offset : offset + 6])}</tg-button-row>'
        )
    blocks.append(
        f'<tg-button-row align="center">{previous}<tg-button type="disabled">{position}/{len(exercises)}</tg-button>{following}</tg-button-row>'
    )
    return InputRichMessage(html="".join(blocks))


def build_workout_dashboard(
    workout_session: WorkoutSession, streak: int = 0
) -> InputRichMessage:
    total = workout_session.sets_total
    done = workout_session.sets_done
    percent = round(done / total * 100) if total else 0
    streak_text = f" · 🔥 <b>{streak}</b>" if streak else ""
    title = workout_session.training_day.name
    if workout_session.is_completed:
        status = "✅ Тренировка выполнена"
    elif done:
        status = f"{done}/{total} подходов · {percent}%"
    else:
        status = f"0/{total} подходов"
    return InputRichMessage(
        html=(
            f"<h3>{escape(title)}</h3>"
            f"<p><b>{status}</b>{streak_text}</p>"
            "<hr/>"
            f"{_set_buttons(workout_session)}"
            "<footer>Отмечай подход сразу после выполнения — прогресс сохранится автоматически.</footer>"
        )
    )


def build_no_workout_message() -> InputRichMessage:
    return simple_rich(
        "Сегодня без тренировки",
        "<p>На сегодня тренировочный день не запланирован.</p><p>Восстановление — часть прогресса.</p>",
        '<tg-button-row><tg-button type="callback_data" data="day:list">Расписание</tg-button></tg-button-row>',
    )


def build_invalid_workout_message(training_day: TrainingDay) -> InputRichMessage:
    return simple_rich(
        training_day.name,
        "<p>Тренировка не собрана: в выбранных группах нет активных упражнений.</p>"
        "<p>Добавь упражнения или пересоздай тренировочный день.</p>",
        '<tg-button-row><tg-button type="callback_data" style="primary" data="exercise:new">Добавить упражнение</tg-button>'
        '<tg-button type="callback_data" data="day:list">Расписание</tg-button></tg-button-row>',
    )


def build_stats_message(
    data: dict, calendar: list[dict], reset_link: str
) -> InputRichMessage:
    icons = {
        "done": "✅",
        "partial": "◐",
        "missed": "✕",
        "pending": "*",
        "empty": " ",
        "future": " ",
    }
    month_names = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ]
    month = next(item["date"] for item in calendar if item["date"] is not None)
    headers = "".join(
        f"<th>{name}</th>" for name in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    )
    rows = []
    for offset in range(0, len(calendar), 7):
        week = calendar[offset : offset + 7]
        cells = "".join(
            "<td></td>"
            if item["date"] is None
            else f'<td align="center"><b>{item["date"].day}</b><br>{icons[item["status"]]}</td>'
            for item in week
        )
        rows.append(f"<tr>{cells}</tr>")

    return InputRichMessage(
        html=(
            "<h3>Статистика тренировок</h3>"
            "<table compact bordered>"
            f'<tr><td>🔥 Текущая серия</td><td align="right"><b>{data["streak"]} трен. дней</b></td></tr>'
            f'<tr><td>🏆 Рекорд серии</td><td align="right"><b>{data["best_streak"]} трен. дней</b></td></tr>'
            f'<tr><td>✅ Выполнено тренировок</td><td align="right"><b>{data["completed_workouts"]}/{data["planned_workouts"]}</b></td></tr>'
            f'<tr><td>💪 Закрыто упражнений</td><td align="right"><b>{data["exercise_instances"]}</b></td></tr>'
            f'<tr><td>🔁 Выполнено подходов</td><td align="right"><b>{data["sets_done"]}</b></td></tr>'
            f'<tr><td>📈 Выполнение плана</td><td align="right"><b>{data["completion"]}%</b></td></tr>'
            "</table>"
            f"<h4>{month_names[month.month - 1]}</h4>"
            f"<table compact><tr>{headers}</tr>{''.join(rows)}</table>"
            "<footer>✅ выполнено · ◐ частично · ✕ пропущено · * сегодня в процессе<br>"
            f'<a href="{escape(reset_link, quote=True)}">Сбросить статистику</a></footer>'
        )
    )


def build_motivation_message(
    title: str, body: str, streak: int = 0
) -> InputRichMessage:
    streak_line = (
        f"<p>🔥 Серия тренировочных дней: <b>{streak}</b></p>" if streak else ""
    )
    return InputRichMessage(
        html=(
            f"<h3>{escape(title)}</h3><p>{escape(body)}</p>{streak_line}"
            '<tg-button-row><tg-button type="callback_data" style="primary" data="workout:today">Открыть тренировку</tg-button></tg-button-row>'
        )
    )
