import os
from dotenv import load_dotenv

# Загрузка переменных из .env файла
load_dotenv()

# ==========================================
# Telegram Bot
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
SEARCH_COOLDOWN = int(os.getenv("SEARCH_COOLDOWN", "60"))  # секунд между поисками

# ==========================================
# GitHub API настройки
# ==========================================
GITHUB_API_URL = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN") or None

# ==========================================
# DeepSeek AI (для анализа результатов парсинга)
# ==========================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

# 1. Chat Completions API (старый) — для анализа результатов парсинга
# Быстрая и дешёвая модель для структурированных данных
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# 2. Responses API (новый) — для свободного веб-поиска с встроенным web_search
# Используется PRO модель — она позволяет проводить более глубокий поиск и анализ
DEEPSEEK_RESPONSES_MODEL = os.getenv("DEEPSEEK_RESPONSES_MODEL", "deepseek-v4-pro")

# ==========================================
# Kimi AI (для свободного веб-поиска) - пока больше не используется
# ==========================================
KIMI_API_KEY = os.getenv("KIMI_API_KEY")
KIMI_BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
KIMI_MODEL = os.getenv("KIMI_MODEL", "kimi-k3")

# Старый блок - уже не используется:
# Флаг: использовать ли Kimi для свободного AI-поиска
# true  → свободный поиск идёт через Kimi с встроенным $web_search
# false → свободный поиск идёт через старую связку (ddgs + DeepSeek)
USE_KIMI_FOR_WEB_SEARCH = os.getenv("USE_KIMI_FOR_WEB_SEARCH", "true").lower() == "true"

# ==========================================
# Общие константы
# ==========================================
CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "30"))          # срок жизни кэша
MAX_TELEGRAM_MESSAGE_LENGTH = 4096                                # лимит длины сообщения в Telegram

# ==========================================
# Проверка обязательных настроек
# ==========================================
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Проверьте файл .env")

print(f"🔑 KIMI_API_KEY загружен: {bool(KIMI_API_KEY)}")
print(f"🔑 DEEPSEEK_API_KEY загружен: {bool(DEEPSEEK_API_KEY)}")