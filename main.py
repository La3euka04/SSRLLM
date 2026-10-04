import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from langchain_core.globals import set_debug

from settings import settings
from src.graph_builder import init_graph, close_graph
from bot.handlers import router
# from src.logger_setup import setup_logging
# setup_logging()

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
        # BotCommand(command="deep", description="Deep research on a question"),
        # BotCommand(command="Fast", description="Deep research on a question"),
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


    # Почему-то сгенерировались 5 поттем но они с обьяснением а не просто топики, а также надо сделать дейолтные ответы кто ты какая твоя задача и для чего ты нужен
    # Плюс надо разобраться с лоикой телеграмма добавить кнопки чтобы топики присылалиь кнопками. и меню начала как бы. плюс меню выхова очистки истории.