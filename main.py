import asyncio
import logging
from aiogram import Bot, Dispatcher
import config
from database.models import init_db
from handlers import admin, admin_panel, client, common, master, reports

logging.basicConfig(level=logging.INFO)


async def main():
    if not config.BOT_TOKEN:
        raise SystemExit("Не задана переменная окружения BOT_TOKEN. Укажите токен бота в настройках хостинга.")

    await init_db()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    dp.include_router(reports.router)
    dp.include_router(admin_panel.router)
    dp.include_router(common.router)
    dp.include_router(client.router)
    dp.include_router(master.router)
    dp.include_router(admin.router)

    logging.info("Starting Telegram Bot Polling...")
    asyncio.create_task(reports.sd_reminder_loop(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
