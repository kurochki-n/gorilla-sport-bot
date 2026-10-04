from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from database.repositories import get_active_exercises
from database.training_editor import (
    active_links,
    change_day_sets,
    editable_day,
    set_day_exercise,
    toggle_day_alternative,
)
from services.rich_messages import edit_rich, simple_rich

router = Router(name=__name__)
PAGE_SIZE = 8


def button(label: str, data: str, style: str = "") -> str:
    style_attr = f' style="{style}"' if style else ""
    return (
        f'<tg-button-row><tg-button type="callback_data"{style_attr}'
        f' data="{data}">{escape(label)}</tg-button></tg-button-row>'
    )


def page_items(items, page):
    last = max(0, (len(items) - 1) // PAGE_SIZE)
    page = max(0, min(page, last))
    return items[page * PAGE_SIZE : (page + 1) * PAGE_SIZE], page, last


def navigation(prefix: str, page: int, last: int) -> str:
    result = ""
    if page > 0:
        result += button("← Назад", f"{prefix}:{page - 1}")
    if page < last:
        result += button("Далее →", f"{prefix}:{page + 1}")
    return result


async def editor_screen(session, user_id, day_id, action, args):
    day = await editable_day(session, user_id, day_id)
    links = active_links(day)
    if action == "open":
        items, page, last = page_items(links, int(args[0]) if args else 0)
        buttons = "".join(
            button(
                f"{link.exercise.name} · {link.sets_count or link.exercise.default_sets} подх.",
                f"editday:exercise:{day_id}:{link.exercise_id}",
            )
            for link in items
        )
        buttons += navigation(f"editday:open:{day_id}", page, last)
        buttons += button("+ Добавить упражнение", f"editday:add:{day_id}:0", "primary")
        buttons += button("Готово · Расписание", "day:list")
        return simple_rich(
            f"Редактирование · {day.name}",
            "<p>Выбери упражнение, чтобы изменить подходы, замены или убрать его.</p>"
            "<p>Изменения сохраняются сразу и применяются к новым тренировкам. "
            "Уже созданные занятия и история сохраняются.</p>",
            buttons,
        )
    if action == "add":
        exercises = await get_active_exercises(session, user_id)
        selected = {link.exercise_id for link in links}
        choices = [
            exercise
            for exercise in exercises
            if exercise.id not in selected and exercise.muscle_group.is_active
        ]
        items, page, last = page_items(choices, int(args[0]))
        buttons = "".join(
            button(
                f"+ {exercise.name} · {exercise.muscle_group.name}",
                f"editday:enable:{day_id}:{exercise.id}:{page}",
            )
            for exercise in items
        )
        buttons += navigation(f"editday:add:{day_id}", page, last)
        buttons += button("← К тренировке", f"editday:open:{day_id}:0")
        return simple_rich(
            "Добавить упражнение",
            "<p>Выбери упражнение из своего каталога.</p>"
            if choices
            else "<p>Все доступные упражнения уже добавлены. Новые можно создать через /newexercise.</p>",
            buttons,
        )

    source_id = int(args[0])
    link = next((item for item in links if item.exercise_id == source_id), None)
    if link is None:
        raise ValueError("Упражнение больше не входит в тренировку")
    if action == "exercise":
        count = link.sets_count or link.exercise.default_sets
        names = [
            item.exercise.name for item in link.alternatives if item.exercise.is_active
        ]
        buttons = (
            "<tg-button-row>"
            f'<tg-button type="callback_data" data="editday:sets:{day_id}:{source_id}:-1">− Подход</tg-button>'
            f'<tg-button type="callback_data" data="editday:sets:{day_id}:{source_id}:1">+ Подход</tg-button>'
            "</tg-button-row>"
        )
        buttons += button("Выбрать замены", f"editday:alt:{day_id}:{source_id}:0")
        buttons += button(
            "Убрать из тренировки", f"editday:remove:{day_id}:{source_id}", "danger"
        )
        buttons += button("← К тренировке", f"editday:open:{day_id}:0")
        return simple_rich(
            link.exercise.name,
            f"<p>Подходы в этой тренировке: <b>{count}</b> (от 1 до 6).</p>"
            f"<p>Замены: {escape(', '.join(names) or 'не выбраны')}.</p>"
            "<p>Количество подходов относится только к этому плану, в том числе при замене упражнения.</p>",
            buttons,
        )
    if action == "alt":
        choices = [
            exercise
            for exercise in await get_active_exercises(
                session, user_id, link.exercise.muscle_group_id
            )
            if exercise.id != source_id
        ]
        selected = {item.exercise_id for item in link.alternatives}
        items, page, last = page_items(choices, int(args[1]))
        buttons = "".join(
            button(
                f"{'✓' if exercise.id in selected else '+'} {exercise.name}",
                f"editday:toggle:{day_id}:{source_id}:{exercise.id}:{page}",
            )
            for exercise in items
        )
        buttons += navigation(f"editday:alt:{day_id}:{source_id}", page, last)
        buttons += button("Готово", f"editday:exercise:{day_id}:{source_id}")
        return simple_rich(
            f"Замены · {link.exercise.name}",
            "<p>Нажми, чтобы добавить или убрать замену. Можно выбрать несколько или ни одной.</p>"
            if choices
            else "<p>Нет других упражнений этой группы. Сначала добавь их через /newexercise.</p>",
            buttons,
        )
    raise ValueError("Неизвестное действие")


@router.callback_query(F.data.startswith("editday:"))
async def edit_training_day(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    parts = callback.data.split(":")
    try:
        action, day_id, args = parts[1], int(parts[2]), parts[3:]
        if action == "enable":
            await set_day_exercise(
                session, callback.from_user.id, day_id, int(args[0]), True
            )
            action, args = "add", [args[1]]
        elif action == "remove":
            await set_day_exercise(
                session, callback.from_user.id, day_id, int(args[0]), False
            )
            action, args = "open", ["0"]
        elif action == "sets":
            await change_day_sets(
                session, callback.from_user.id, day_id, int(args[0]), int(args[1])
            )
            action, args = "exercise", [args[0]]
        elif action == "toggle":
            await toggle_day_alternative(
                session, callback.from_user.id, day_id, int(args[0]), int(args[1])
            )
            action, args = "alt", [args[0], args[2]]
        screen = await editor_screen(
            session, callback.from_user.id, day_id, action, args
        )
    except (ValueError, IndexError) as error:
        await callback.answer(str(error) or "Некорректное действие", show_alert=True)
        return
    await state.clear()
    if callback.message:
        await edit_rich(
            callback.bot, callback.message.chat.id, callback.message.message_id, screen
        )
    await callback.answer()
