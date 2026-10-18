import sys
from pathlib import Path
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from src.settings import settings
from src.graph_builder import init_graph, close_graph
from bot.handlers import router

sys.path.insert(0, str(Path(__file__).resolve().parent))
TELEGRAM_BOT_TOKEN = settings.TELEGRAM_BOT_TOKEN
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# set_debug(True)


async def main():
    await init_graph()
    logger.info("Graph initialized")

    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands([
        BotCommand(command="start", description="Main menu"),
        BotCommand(command="mode", description="Choose answer mode"),
        BotCommand(command="limit", description="Deep research left today"),
        BotCommand(command="clear", description="Clear history and PDFs"),
        BotCommand(command="help", description="How to use the bot"),
    ])
    dp = Dispatcher()
    dp.include_router(router)

    try:
        await dp.start_polling(bot)
    finally:
        await close_graph()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
