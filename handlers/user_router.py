from __future__ import annotations

from datetime import date, datetime, time, timezone
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.methods import SendRichMessage
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from config_reader import get_settings
from database.models import User
from database.repositories import (
    create_exercise,
    create_muscle_group,
    create_training_day,
    deactivate_exercise,
    deactivate_muscle_group,
    deactivate_training_day,
    generate_workout_session,
    get_active_exercises,
    get_active_muscle_groups,
    get_active_training_days,
    get_exercise,
    get_muscle_group,
    get_training_day,
    mark_workout_set_done,
    reset_statistics,
    upsert_user,
)
from handlers.states import CreateExercise, CreateMuscleGroup, CreateTrainingDay
from services.rich_messages import (
    build_day_groups_picker,
    build_exercise_delete_confirmation,
    build_exercise_group_picker,
    build_exercises_message,
    build_group_count_message,
    build_group_delete_confirmation,
    build_groups_message,
    build_invalid_workout_message,
    build_motivation_message,
    build_no_workout_message,
    build_stats_message,
    build_training_day_delete_confirmation,
    build_training_days_message,
    build_weekdays_message,
    build_workout_dashboard,
    edit_rich,
    send_rich,
    simple_rich,
)
from services.workouts import calendar_data, scheduled_training_days, stats, streaks
from utils.dates import mask_to_text

router = Router(name=__name__)

MOSCOW_TIMEZONES = {
    -1: "Europe/Kaliningrad",
    0: "Europe/Moscow",
    1: "Europe/Samara",
    2: "Asia/Yekaterinburg",
    3: "Asia/Omsk",
    4: "Asia/Krasnoyarsk",
    5: "Asia/Irkutsk",
    6: "Asia/Yakutsk",
    7: "Asia/Vladivostok",
    8: "Asia/Magadan",
    9: "Asia/Kamchatka",
}


def offset_from_moscow(timezone_name: str) -> int | None:
    try:
        now = datetime.now(timezone.utc)
        local_offset = now.astimezone(ZoneInfo(timezone_name)).utcoffset()
        moscow_offset = now.astimezone(ZoneInfo("Europe/Moscow")).utcoffset()
    except ZoneInfoNotFoundError:
        return None
    if local_offset is None or moscow_offset is None:
        return None
    difference_seconds = int((local_offset - moscow_offset).total_seconds())
    if difference_seconds % 3600:
        return None
    return difference_seconds // 3600


def format_moscow_offset(offset: int | None) -> str:
    if offset is None:
        return "Неизвестное смещение от Москвы"
    if offset == 0:
        return "По московскому времени"
    return f"{offset:+d} ч. от Москвы"


async def local_now(session: AsyncSession, user_id: int) -> datetime:
    user = await session.get(User, user_id)
    timezone_name = user.timezone if user else get_settings().default_timezone
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo(get_settings().default_timezone)
    return datetime.now(timezone.utc).astimezone(zone)


async def local_today(session: AsyncSession, user_id: int) -> date:
    return (await local_now(session, user_id)).date()


async def send_screen(message: Message, rich_message, reply_markup=None):
    return await message.bot(
        SendRichMessage(
            chat_id=message.chat.id,
            rich_message=rich_message,
            reply_markup=reply_markup,
        )
    )


async def ensure_user(message: Message, session: AsyncSession) -> None:
    await upsert_user(
        session,
        message.from_user.id,
        message.from_user.first_name,
        message.from_user.last_name,
        message.from_user.username,
        get_settings().default_timezone,
    )


@router.message(CommandStart(deep_link=True, magic=F.args == "reset_stats"))
async def reset_statistics_prompt(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    await state.clear()
    await ensure_user(message, session)
    await send_screen(
        message,
        simple_rich(
            "Сбросить статистику?",
            "<p>Будет безвозвратно удалена вся история тренировок: выполненные подходы, прогресс, серии и календарь.</p>"
            "<p>Тренировочные дни, упражнения и группы мышц останутся без изменений.</p>",
            '<tg-button-row><tg-button type="callback_data" style="danger" data="stats:reset:confirm">Да, сбросить</tg-button>'
            '<tg-button type="callback_data" data="stats:reset:cancel">Отмена</tg-button></tg-button-row>',
        ),
    )


@router.message(CommandStart())
async def start(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await ensure_user(message, session)
    await send_screen(
        message,
        simple_rich(
            "Тренировки",
            "<p>Собери собственную библиотеку упражнений, настрой тренировочные дни — бот сам будет формировать тренировку и присылать её по расписанию.</p>"
            "<p><b>Ротация без повторов:</b> упражнения перемешиваются и выходят из очереди после использования, поэтому одни и те же движения не выпадают постоянно.</p>",
            '<tg-button-row><tg-button type="callback_data" style="primary" data="group:new">Создать группу мышц</tg-button></tg-button-row>',
        ),
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await send_screen(
        message,
        simple_rich(
            "Команды",
            "<table compact>"
            "<tr><td><b>/newgroup</b></td><td>добавить группу мышц</td></tr>"
            "<tr><td><b>/newexercise</b></td><td>добавить упражнение</td></tr>"
            "<tr><td><b>/newday</b></td><td>создать тренировочный день</td></tr>"
            "<tr><td><b>/today</b></td><td>тренировка на сегодня</td></tr>"
            "<tr><td><b>/groups</b></td><td>группы мышц и удаление</td></tr>"
            "<tr><td><b>/exercises</b></td><td>упражнения и удаление</td></tr>"
            "<tr><td><b>/days</b></td><td>расписание и удаление</td></tr>"
            "<tr><td><b>/stats</b></td><td>календарь и статистика</td></tr>"
            "<tr><td><b>/timezone</b></td><td>часовой пояс</td></tr>"
            "<tr><td><b>/cancel</b></td><td>отменить текущее создание</td></tr>"
            "</table>",
        ),
    )


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    await state.clear()
    if current:
        await send_screen(
            message, simple_rich("Отменено", "<p>Текущее действие отменено.</p>")
        )
    else:
        await send_screen(
            message,
            simple_rich(
                "Нечего отменять", "<p>Сейчас нет незавершённого действия.</p>"
            ),
        )


# --- Muscle groups ---


async def begin_new_group(bot, chat_id: int, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateMuscleGroup.name)
    await send_rich(
        bot,
        chat_id,
        simple_rich(
            "Новая группа мышц",
            "<p>Отправь название группы.</p><p><i>Например: Спина, Грудь, Бицепс, Ноги.</i></p>",
        ),
    )


@router.message(Command("newgroup"))
async def new_group(message: Message, state: FSMContext, session: AsyncSession) -> None:
    await ensure_user(message, session)
    await begin_new_group(message.bot, message.chat.id, state)


@router.callback_query(F.data == "group:new")
async def new_group_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await begin_new_group(callback.bot, callback.from_user.id, state)
    await callback.answer()


@router.message(CreateMuscleGroup.name)
async def group_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 80:
        await send_screen(
            message,
            simple_rich(
                "Не подходит", "<p>Название должно быть от 1 до 80 символов.</p>"
            ),
        )
        return
    existing = await get_active_muscle_groups(session, message.from_user.id)
    if any(group.name.casefold() == name.casefold() for group in existing):
        await send_screen(
            message,
            simple_rich("Такая группа уже есть", "<p>Используй другое название.</p>"),
        )
        return
    group = await create_muscle_group(session, message.from_user.id, name)
    await state.clear()
    await send_screen(
        message,
        simple_rich(
            "Группа создана",
            f"<p><b>{escape(group.name)}</b></p><p>Теперь добавь в неё упражнения.</p>",
            '<tg-button-row><tg-button type="callback_data" style="primary" data="exercise:new">Добавить упражнение</tg-button>'
            '<tg-button type="callback_data" data="group:new">Ещё группу</tg-button></tg-button-row>',
        ),
    )


@router.message(Command("groups"))
async def groups_list(message: Message, session: AsyncSession) -> None:
    groups = await get_active_muscle_groups(session, message.from_user.id)
    await send_screen(message, build_groups_message(groups))


@router.callback_query(F.data == "group:list")
async def groups_list_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    groups = await get_active_muscle_groups(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_groups_message(groups),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("group:delete:"))
async def delete_group_prompt(callback: CallbackQuery, session: AsyncSession) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    group = await get_muscle_group(session, callback.from_user.id, group_id)
    if group is None or not group.is_active:
        await callback.answer("Группа уже удалена", show_alert=True)
        return
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_group_delete_confirmation(group),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("group:confirm_delete:"))
async def delete_group_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    group = await deactivate_muscle_group(session, callback.from_user.id, group_id)
    if group is None:
        await callback.answer("Группа уже удалена", show_alert=True)
        return
    groups = await get_active_muscle_groups(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_groups_message(groups),
        )
    await callback.answer(f"{group.name} удалена")


@router.callback_query(F.data == "group:cancel_delete")
async def delete_group_cancel(callback: CallbackQuery, session: AsyncSession) -> None:
    groups = await get_active_muscle_groups(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_groups_message(groups),
        )
    await callback.answer()


# --- Exercises ---


async def begin_new_exercise(
    bot, chat_id: int, user_id: int, state: FSMContext, session: AsyncSession
) -> None:
    groups = await get_active_muscle_groups(session, user_id)
    if not groups:
        await send_rich(
            bot,
            chat_id,
            simple_rich(
                "Сначала создай группу",
                "<p>Упражнение должно принадлежать группе мышц.</p>",
                '<tg-button-row><tg-button type="callback_data" style="primary" data="group:new">Создать группу</tg-button></tg-button-row>',
            ),
        )
        return
    await state.clear()
    await state.set_state(CreateExercise.muscle_group)
    await send_rich(bot, chat_id, build_exercise_group_picker(groups))


@router.message(Command("newexercise"))
async def new_exercise(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await ensure_user(message, session)
    await begin_new_exercise(
        message.bot, message.chat.id, message.from_user.id, state, session
    )


@router.callback_query(F.data == "exercise:new")
async def new_exercise_callback(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await begin_new_exercise(
        callback.bot, callback.from_user.id, callback.from_user.id, state, session
    )
    await callback.answer()


@router.callback_query(
    CreateExercise.muscle_group, F.data.startswith("exercise:group:")
)
async def exercise_choose_group(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    group_id = int(callback.data.rsplit(":", 1)[1])
    group = await get_muscle_group(session, callback.from_user.id, group_id)
    if group is None or not group.is_active:
        await callback.answer("Группа недоступна", show_alert=True)
        return
    await state.update_data(muscle_group_id=group.id, muscle_group_name=group.name)
    await state.set_state(CreateExercise.name)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            simple_rich(
                "Новое упражнение · 2/5",
                f"<p>Группа: <b>{escape(group.name)}</b></p><p>Отправь название упражнения.</p>"
                "<p><i>Например: Тяга верхнего блока.</i></p>",
            ),
        )
    await callback.answer()


@router.message(CreateExercise.name)
async def exercise_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 100:
        await send_screen(
            message,
            simple_rich(
                "Не подходит", "<p>Название должно быть от 1 до 100 символов.</p>"
            ),
        )
        return
    await state.update_data(name=name)
    await state.set_state(CreateExercise.sets)
    buttons = "".join(
        f'<tg-button type="callback_data" style="primary" data="exercise:sets:{count}">{count}</tg-button>'
        for count in range(1, 7)
    )
    await send_screen(
        message,
        simple_rich(
            "Новое упражнение · 3/5",
            "<p>Сколько подходов выполнять по умолчанию?</p>",
            f'<tg-button-row align="left">{buttons}</tg-button-row>',
        ),
    )


@router.callback_query(CreateExercise.sets, F.data.startswith("exercise:sets:"))
async def exercise_sets(callback: CallbackQuery, state: FSMContext) -> None:
    sets_count = int(callback.data.rsplit(":", 1)[1])
    if not 1 <= sets_count <= 6:
        await callback.answer("Недопустимое число подходов", show_alert=True)
        return
    await state.update_data(default_sets=sets_count)
    await state.set_state(CreateExercise.target)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            simple_rich(
                "Новое упражнение · 4/5",
                "<p>Отправь цель одного подхода.</p>"
                "<p><i>Например: 8–12 повторений, 10 повторений, 40 секунд.</i></p>",
            ),
        )
    await callback.answer()


@router.message(CreateExercise.target)
async def exercise_target(message: Message, state: FSMContext) -> None:
    target = (message.text or "").strip()
    if not 1 <= len(target) <= 100:
        await send_screen(
            message,
            simple_rich(
                "Не подходит", "<p>Описание должно быть от 1 до 100 символов.</p>"
            ),
        )
        return
    await state.update_data(target_text=target)
    await state.set_state(CreateExercise.rest)
    await send_screen(
        message,
        simple_rich(
            "Новое упражнение · 5/5",
            "<p>Сколько отдыхать между подходами?</p>",
            '<tg-button-row align="left">'
            '<tg-button type="callback_data" data="exercise:rest:60">60 сек</tg-button>'
            '<tg-button type="callback_data" style="primary" data="exercise:rest:90">90 сек</tg-button>'
            '<tg-button type="callback_data" data="exercise:rest:120">120 сек</tg-button>'
            '<tg-button type="callback_data" data="exercise:rest:180">180 сек</tg-button>'
            "</tg-button-row>",
        ),
    )


@router.callback_query(CreateExercise.rest, F.data.startswith("exercise:rest:"))
async def exercise_rest(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    rest_seconds = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    group = await get_muscle_group(
        session, callback.from_user.id, int(data["muscle_group_id"])
    )
    if group is None or not group.is_active:
        await state.clear()
        await callback.answer("Группа была удалена", show_alert=True)
        return
    exercise = await create_exercise(
        session,
        callback.from_user.id,
        group.id,
        data["name"],
        int(data["default_sets"]),
        data["target_text"],
        rest_seconds,
    )
    await state.clear()
    result = simple_rich(
        "Упражнение добавлено",
        f"<p><b>{escape(exercise.name)}</b><br>{escape(group.name)} · {exercise.default_sets} × "
        f"{escape(exercise.target_text)} · отдых {exercise.rest_seconds} сек</p>",
        '<tg-button-row><tg-button type="callback_data" style="primary" data="exercise:new">Добавить ещё</tg-button>'
        '<tg-button type="callback_data" data="exercise:list">Все упражнения</tg-button></tg-button-row>',
    )
    if callback.message:
        await edit_rich(
            callback.bot, callback.message.chat.id, callback.message.message_id, result
        )
    else:
        await send_rich(callback.bot, callback.from_user.id, result)
    await callback.answer("Добавлено")


@router.message(Command("exercises"))
async def exercises_list(message: Message, session: AsyncSession) -> None:
    exercises = await get_active_exercises(session, message.from_user.id)
    await send_screen(message, build_exercises_message(exercises))


@router.callback_query(F.data == "exercise:list")
async def exercises_list_callback(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    exercises = await get_active_exercises(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_exercises_message(exercises),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("exercise:delete:"))
async def delete_exercise_prompt(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    exercise_id = int(callback.data.rsplit(":", 1)[1])
    exercise = await get_exercise(session, callback.from_user.id, exercise_id)
    if exercise is None or not exercise.is_active:
        await callback.answer("Упражнение уже удалено", show_alert=True)
        return
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_exercise_delete_confirmation(exercise),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("exercise:confirm_delete:"))
async def delete_exercise_confirm(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    exercise_id = int(callback.data.rsplit(":", 1)[1])
    exercise = await deactivate_exercise(session, callback.from_user.id, exercise_id)
    if exercise is None:
        await callback.answer("Упражнение уже удалено", show_alert=True)
        return
    exercises = await get_active_exercises(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_exercises_message(exercises),
        )
    await callback.answer(f"{exercise.name} удалено")


@router.callback_query(F.data == "exercise:cancel_delete")
async def delete_exercise_cancel(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    exercises = await get_active_exercises(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_exercises_message(exercises),
        )
    await callback.answer()


# --- Training days ---


async def eligible_groups(session: AsyncSession, user_id: int):
    groups = await get_active_muscle_groups(session, user_id)
    return [
        group
        for group in groups
        if any(exercise.is_active for exercise in group.exercises)
    ]


async def begin_new_training_day(
    bot, chat_id: int, user_id: int, state: FSMContext, session: AsyncSession
) -> None:
    groups = await eligible_groups(session, user_id)
    if not groups:
        await send_rich(
            bot,
            chat_id,
            simple_rich(
                "Нужны упражнения",
                "<p>Чтобы создать тренировочный день, должна быть хотя бы одна группа мышц с активным упражнением.</p>",
                '<tg-button-row><tg-button type="callback_data" style="primary" data="group:new">Добавить группу</tg-button>'
                '<tg-button type="callback_data" data="exercise:new">Добавить упражнение</tg-button></tg-button-row>',
            ),
        )
        return
    await state.clear()
    await state.set_state(CreateTrainingDay.name)
    await send_rich(
        bot,
        chat_id,
        simple_rich(
            "Новый тренировочный день · 1/4",
            "<p>Как назвать тренировку?</p><p><i>Например: Спина + трицепс или День A.</i></p>",
        ),
    )


@router.message(Command("newday"))
async def new_training_day(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    await ensure_user(message, session)
    await begin_new_training_day(
        message.bot, message.chat.id, message.from_user.id, state, session
    )


@router.callback_query(F.data == "day:new")
async def new_training_day_callback(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    await begin_new_training_day(
        callback.bot, callback.from_user.id, callback.from_user.id, state, session
    )
    await callback.answer()


@router.message(CreateTrainingDay.name)
async def training_day_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not 1 <= len(name) <= 100:
        await send_screen(
            message,
            simple_rich(
                "Не подходит", "<p>Название должно быть от 1 до 100 символов.</p>"
            ),
        )
        return
    await state.update_data(name=name, weekdays_mask=0)
    await state.set_state(CreateTrainingDay.weekdays)
    await send_screen(message, build_weekdays_message())


@router.callback_query(CreateTrainingDay.weekdays, F.data.startswith("day:weekday:"))
async def training_day_weekdays(callback: CallbackQuery, state: FSMContext) -> None:
    action = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    mask = int(data.get("weekdays_mask", 0))

    if action == "all":
        mask = 127
    elif action == "done":
        if mask == 0:
            await callback.answer("Выбери хотя бы один день", show_alert=True)
            return
        await state.update_data(weekdays_mask=mask)
        await state.set_state(CreateTrainingDay.reminder_time)
        if callback.message:
            await edit_rich(
                callback.bot,
                callback.message.chat.id,
                callback.message.message_id,
                simple_rich(
                    "Новый тренировочный день · 2/4",
                    f"<p>Расписание: <b>{escape(mask_to_text(mask))}</b></p>"
                    "<p>Во сколько присылать тренировку? Отправь время как <b>12:00</b> или <b>18:30</b>.</p>",
                ),
            )
        await callback.answer()
        return
    else:
        index = int(action)
        mask ^= 1 << index

    await state.update_data(weekdays_mask=mask)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_weekdays_message(mask),
        )
    await callback.answer()


@router.message(CreateTrainingDay.reminder_time)
async def training_day_time(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    try:
        hours, minutes = map(int, (message.text or "").strip().split(":"))
        reminder = time(hours, minutes)
    except (ValueError, TypeError):
        await send_screen(
            message,
            simple_rich("Неверное время", "<p>Используй формат <b>18:30</b>.</p>"),
        )
        return

    groups = await eligible_groups(session, message.from_user.id)
    if not groups:
        await state.clear()
        await send_screen(
            message,
            simple_rich(
                "Нет доступных упражнений",
                "<p>Добавь упражнения и создай день заново.</p>",
            ),
        )
        return

    await state.update_data(
        reminder_time=reminder.strftime("%H:%M"), selected_group_ids=[]
    )
    await state.set_state(CreateTrainingDay.groups)
    await send_screen(message, build_day_groups_picker(groups, set()))


@router.callback_query(CreateTrainingDay.groups, F.data.startswith("day:group:"))
async def training_day_groups(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    action = callback.data.rsplit(":", 1)[1]
    groups = await eligible_groups(session, callback.from_user.id)
    valid_ids = {group.id for group in groups}
    data = await state.get_data()
    selected = list(data.get("selected_group_ids", []))

    if action == "done":
        selected = [group_id for group_id in selected if group_id in valid_ids]
        if not selected:
            await callback.answer("Выбери хотя бы одну группу", show_alert=True)
            return
        await state.update_data(
            selected_group_ids=selected, group_count_index=0, group_counts={}
        )
        await state.set_state(CreateTrainingDay.group_count)
        first_group = next(group for group in groups if group.id == selected[0])
        max_count = min(
            5, sum(1 for exercise in first_group.exercises if exercise.is_active)
        )
        if callback.message:
            await edit_rich(
                callback.bot,
                callback.message.chat.id,
                callback.message.message_id,
                build_group_count_message(first_group, max_count, 1, len(selected)),
            )
        await callback.answer()
        return

    group_id = int(action)
    if group_id not in valid_ids:
        await callback.answer("Группа недоступна", show_alert=True)
        return
    if group_id in selected:
        selected.remove(group_id)
    else:
        selected.append(group_id)
    await state.update_data(selected_group_ids=selected)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_day_groups_picker(groups, set(selected)),
        )
    await callback.answer()


@router.callback_query(CreateTrainingDay.group_count, F.data.startswith("day:count:"))
async def training_day_group_count(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    count = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    selected = [int(value) for value in data.get("selected_group_ids", [])]
    index = int(data.get("group_count_index", 0))
    if index >= len(selected):
        await state.clear()
        await callback.answer("Создание уже завершено", show_alert=True)
        return

    group = await get_muscle_group(session, callback.from_user.id, selected[index])
    if group is None or not group.is_active:
        await state.clear()
        await callback.answer(
            "Одна из групп была удалена. Создай день заново.", show_alert=True
        )
        return
    max_count = min(5, sum(1 for exercise in group.exercises if exercise.is_active))
    if not 1 <= count <= max_count:
        await callback.answer("Недопустимое количество", show_alert=True)
        return

    group_counts = dict(data.get("group_counts", {}))
    group_counts[str(group.id)] = count
    index += 1
    await state.update_data(group_counts=group_counts, group_count_index=index)

    if index < len(selected):
        next_group = await get_muscle_group(
            session, callback.from_user.id, selected[index]
        )
        if next_group is None or not next_group.is_active:
            await state.clear()
            await callback.answer(
                "Одна из групп была удалена. Создай день заново.", show_alert=True
            )
            return
        next_max = min(
            5, sum(1 for exercise in next_group.exercises if exercise.is_active)
        )
        if callback.message:
            await edit_rich(
                callback.bot,
                callback.message.chat.id,
                callback.message.message_id,
                build_group_count_message(
                    next_group, next_max, index + 1, len(selected)
                ),
            )
        await callback.answer()
        return

    latest = await state.get_data()
    hours, minutes = map(int, latest["reminder_time"].split(":"))
    pairs = [(group_id, int(group_counts[str(group_id)])) for group_id in selected]
    training_day = await create_training_day(
        session,
        callback.from_user.id,
        latest["name"],
        int(latest["weekdays_mask"]),
        time(hours, minutes),
        pairs,
    )
    await state.clear()
    group_text = ", ".join(
        f"{link.muscle_group.name} × {link.exercise_count}"
        for link in sorted(training_day.muscle_groups, key=lambda item: item.position)
    )
    result = simple_rich(
        "Тренировочный день создан",
        f"<p><b>{escape(training_day.name)}</b><br>{escape(mask_to_text(training_day.weekdays_mask))} · "
        f"{training_day.reminder_time.strftime('%H:%M')}</p><p>{escape(group_text)}</p>"
        "<p>В назначенный день бот автоматически соберёт упражнения через ротацию без частых повторов.</p>",
        '<tg-button-row><tg-button type="callback_data" style="primary" data="day:new">Добавить ещё</tg-button>'
        '<tg-button type="callback_data" data="day:list">Расписание</tg-button></tg-button-row>',
    )
    if callback.message:
        await edit_rich(
            callback.bot, callback.message.chat.id, callback.message.message_id, result
        )
    else:
        await send_rich(callback.bot, callback.from_user.id, result)
    await callback.answer("Создано")


@router.message(Command("days"))
async def training_days_list(message: Message, session: AsyncSession) -> None:
    training_days = await get_active_training_days(session, message.from_user.id)
    await send_screen(message, build_training_days_message(training_days))


@router.callback_query(F.data == "day:list")
async def training_days_list_callback(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    training_days = await get_active_training_days(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_training_days_message(training_days),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("day:delete:"))
async def delete_training_day_prompt(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    training_day_id = int(callback.data.rsplit(":", 1)[1])
    training_day = await get_training_day(
        session, callback.from_user.id, training_day_id
    )
    if training_day is None or not training_day.is_active:
        await callback.answer("Тренировочный день уже удалён", show_alert=True)
        return
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_training_day_delete_confirmation(training_day),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("day:confirm_delete:"))
async def delete_training_day_confirm(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    training_day_id = int(callback.data.rsplit(":", 1)[1])
    today = await local_today(session, callback.from_user.id)
    training_day = await deactivate_training_day(
        session, callback.from_user.id, training_day_id, today
    )
    if training_day is None:
        await callback.answer("Тренировочный день уже удалён", show_alert=True)
        return
    training_days = await get_active_training_days(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_training_days_message(training_days),
        )
    await callback.answer(f"{training_day.name} удалён")


@router.callback_query(F.data == "day:cancel_delete")
async def delete_training_day_cancel(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    training_days = await get_active_training_days(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_training_days_message(training_days),
        )
    await callback.answer()


# --- Workouts ---


async def show_today(bot, chat_id: int, user_id: int, session: AsyncSession) -> None:
    now = await local_now(session, user_id)
    today = now.date()
    training_days = await scheduled_training_days(session, user_id, today)
    if not training_days:
        await send_rich(bot, chat_id, build_no_workout_message())
        return

    current_streak, _ = await streaks(session, user_id, today)
    for training_day in training_days:
        workout = await generate_workout_session(session, training_day, today)
        if workout is None:
            await send_rich(bot, chat_id, build_invalid_workout_message(training_day))
            continue
        sent = await send_rich(
            bot, chat_id, build_workout_dashboard(workout, current_streak)
        )
        workout.telegram_message_id = sent.message_id
        if workout.sent_at is None and (now.hour, now.minute) >= (
            training_day.reminder_time.hour,
            training_day.reminder_time.minute,
        ):
            workout.sent_at = datetime.now(timezone.utc)
        await session.commit()


@router.message(Command("today"))
async def today(message: Message, session: AsyncSession) -> None:
    await show_today(message.bot, message.chat.id, message.from_user.id, session)


@router.callback_query(F.data == "workout:today")
async def today_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await show_today(
        callback.bot, callback.from_user.id, callback.from_user.id, session
    )
    await callback.answer()


@router.callback_query(F.data.startswith("workout:set:"))
async def complete_set(callback: CallbackQuery, session: AsyncSession) -> None:
    set_id = int(callback.data.rsplit(":", 1)[1])
    (
        workout,
        exercise,
        just_exercise_completed,
        just_workout_completed,
    ) = await mark_workout_set_done(
        session,
        callback.from_user.id,
        set_id,
    )
    if workout is None:
        await callback.answer("Этот подход больше недоступен", show_alert=True)
        return

    current_streak, _ = await streaks(
        session, callback.from_user.id, workout.scheduled_date
    )
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            build_workout_dashboard(workout, current_streak),
        )

    if just_workout_completed:
        today = await local_today(session, callback.from_user.id)
        data = await stats(session, callback.from_user.id, today)
        streak = int(data["streak"])
        best = int(data["best_streak"])
        milestones = {3, 5, 10, 20, 30, 50, 75, 100}
        if streak in milestones:
            title = f"Серия {streak} тренировочных дней"
            body = "План снова выполнен без пропуска. Ритм уже становится системой."
        elif streak == best and streak > 1:
            title = "Новый рекорд серии"
            body = (
                f"Личный рекорд обновлён: {streak} тренировочных дней подряд по плану."
            )
        elif streak <= 1:
            title = "Тренировка завершена"
            body = (
                "Все подходы закрыты. Первый тренировочный день новой серии выполнен."
            )
        else:
            title = "Тренировка выполнена"
            body = (
                f"Все подходы закрыты. Серия продолжается: {streak} тренировочных дней."
            )
        await send_rich(
            callback.bot,
            callback.from_user.id,
            build_motivation_message(title, body, streak),
        )
        await callback.answer("Тренировка выполнена!")
    elif just_exercise_completed and exercise is not None:
        await callback.answer(f"{exercise.exercise_name} выполнено ✓")
    else:
        await callback.answer("Подход засчитан ✓")


# --- Statistics and settings ---


@router.message(Command("stats"))
async def statistics(message: Message, session: AsyncSession) -> None:
    today = await local_today(session, message.from_user.id)
    data = await stats(session, message.from_user.id, today)
    calendar = await calendar_data(session, message.from_user.id, today)
    bot_info = await message.bot.get_me()
    reset_link = f"https://t.me/{bot_info.username}?start=reset_stats"
    await send_screen(message, build_stats_message(data, calendar, reset_link))


@router.callback_query(F.data == "stats:reset:confirm")
async def reset_statistics_confirm(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    deleted_sessions = await reset_statistics(session, callback.from_user.id)
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            simple_rich(
                "Статистика сброшена",
                f"<p>Удалено тренировок из истории: <b>{deleted_sessions}</b>.</p>"
                "<p>Тренировочные дни, упражнения и группы мышц сохранены.</p>",
            ),
        )
    await callback.answer("Статистика сброшена")


@router.callback_query(F.data == "stats:reset:cancel")
async def reset_statistics_cancel(callback: CallbackQuery) -> None:
    if callback.message:
        await edit_rich(
            callback.bot,
            callback.message.chat.id,
            callback.message.message_id,
            simple_rich("Сброс отменён", "<p>Статистика не изменена.</p>"),
        )
    await callback.answer()


@router.message(Command("timezone"))
async def timezone_command(message: Message, session: AsyncSession) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 1:
        user = await session.get(User, message.from_user.id)
        current = user.timezone if user else get_settings().default_timezone
        await send_screen(
            message,
            simple_rich(
                "Часовой пояс",
                f"<p>Текущий: <b>{format_moscow_offset(offset_from_moscow(current))}</b></p>"
                "<p>Чтобы изменить, укажи разницу с Москвой:<br>"
                "<code>/timezone +1</code> — на час впереди Москвы<br>"
                "<code>/timezone -1</code> — на час позади Москвы<br>"
                "<code>/timezone 0</code> — московское время</p>",
            ),
        )
        return

    try:
        offset = int(parts[1].strip())
    except ValueError:
        offset = None
    timezone_name = MOSCOW_TIMEZONES.get(offset) if offset is not None else None
    if timezone_name is None:
        await send_screen(
            message,
            simple_rich(
                "Неверное смещение",
                "<p>Укажи целое число от <b>-1</b> до <b>+9</b> относительно Москвы.</p>"
                "<p>Например: <code>/timezone +1</code> для Самары.</p>",
            ),
        )
        return

    user = await session.get(User, message.from_user.id)
    if user is None:
        await upsert_user(
            session,
            message.from_user.id,
            message.from_user.first_name,
            message.from_user.last_name,
            message.from_user.username,
            timezone_name,
        )
        user = await session.get(User, message.from_user.id)
    user.timezone = timezone_name
    await session.commit()
    await send_screen(
        message,
        simple_rich(
            "Часовой пояс изменён",
            f"<p><b>{format_moscow_offset(offset)}</b></p>",
        ),
    )
