"""Запуск: python -m bot"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.config import load_config
from bot.handlers import router
from bot.orders import load_menu
from bot.storage import Storage


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    storage = Storage(config.db_path)
    await storage.connect()

    session = AiohttpSession(proxy=config.proxy) if config.proxy else None
    bot = Bot(config.bot_token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # «storage» у Dispatcher занято хранилищем FSM, поэтому orders_db
    dp = Dispatcher(config=config, orders_db=storage, menu=load_menu())
    dp.include_router(router)
    try:
        await dp.start_polling(bot)
    finally:
        await storage.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
