import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config_reader import get_settings
from database.session import close_db, init_db
from handlers.user_router import router as user_router
from middlewares.db import DbSessionMiddleware
from services.scheduler import scheduler_loop


BOT_COMMANDS = [
    BotCommand(command="start", description="Начать работу с ботом"),
    BotCommand(command="help", description="Список команд"),
    BotCommand(command="today", description="Тренировка на сегодня"),
    BotCommand(command="stats", description="Статистика тренировок"),
    BotCommand(command="groups", description="Группы мышц"),
    BotCommand(command="newgroup", description="Добавить группу мышц"),
    BotCommand(command="exercises", description="Список упражнений"),
    BotCommand(command="newexercise", description="Добавить упражнение"),
    BotCommand(command="days", description="Тренировочные дни"),
    BotCommand(command="newday", description="Создать тренировочный день"),
    BotCommand(command="timezone", description="Настроить часовой пояс"),
    BotCommand(command="cancel", description="Отменить текущее действие"),
]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    settings = get_settings()
    await init_db()

    bot = Bot(
        settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    await bot.set_my_commands(BOT_COMMANDS)

    dp = Dispatcher(storage=MemoryStorage())
    dp.update.middleware(DbSessionMiddleware())
    dp.include_router(user_router)

    scheduler_task = asyncio.create_task(scheduler_loop(bot), name="workout-scheduler")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler_task.cancel()
        await asyncio.gather(scheduler_task, return_exceptions=True)
        await bot.session.close()
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
