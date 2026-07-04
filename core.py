import logging
import asyncio
from aiogram import Bot
from config import BOT_TOKEN

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Инициализация бота
bot = Bot(token=BOT_TOKEN)

# Глобальные словари для хранения состояний между запросами
user_last_search = {}  # {user_id: timestamp}
cancel_events = {}     # {user_id: asyncio.Event}
pending_cache_queries = {} # {user_id: {"search_type": "fio"/"phone", "search_value": "...", "source": "..."}}