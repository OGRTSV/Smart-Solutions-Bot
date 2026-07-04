import asyncio
import logging
import signal

from aiogram import Dispatcher
from aiogram.exceptions import TelegramServerError, TelegramNetworkError

from core import bot
from handlers import start, search_menu, fio_search, phone_search, plate_search
from handlers.cache_handlers import router as cache_router
from utils.database import init_database
from handlers.history import router as history_router
from handlers.github_search import router as github_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

dp = Dispatcher()

# Подключаем все роутеры (обработчики)
dp.include_routers(
    github_router,   # GitHub — первым (там тоже состояния)
    history_router,         # История — раньше start
    fio_search.router,      # ФИО — ДО start
    phone_search.router,    # Телефон — ДО start
    plate_search.router,    # Госномер — ДО start
    search_menu.router,     # Меню поиска
    cache_router,           # Обработчики кэша
    start.router,           # Start и F.text — ПОСЛЕДНИМ
)


async def shutdown():
    logging.info("Остановка бота...")

async def main():
    logging.info("Запуск бота...")

    # Создаем таблицы в БД, если их нет
    init_database()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.ensure_future(shutdown()))
        except NotImplementedError:
            pass

    retry_delay = 5
    while True:
        try:
            logging.info("🔄 Подключение к Telegram API...")
            await dp.start_polling(bot)
            break
        except (TelegramServerError, TelegramNetworkError) as e:
            logging.warning(f"⚠️ Ошибка связи с Telegram ({e.__class__.__name__}). Повторная попытка через {retry_delay} сек...")
            await asyncio.sleep(retry_delay)
        except Exception as e:
            logging.error(f"❌ Непредвиденная ошибка при работе бота: {e}", exc_info=True)
            logging.info(f"🔄 Перезапуск через {retry_delay} сек...")
            await asyncio.sleep(retry_delay)

if __name__ == "__main__":
    asyncio.run(main())