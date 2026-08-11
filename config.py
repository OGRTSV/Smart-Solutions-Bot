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
# DeepSeek AI
# ==========================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-v4-flash"

# ==========================================
# Проверка обязательных настроек
# ==========================================
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не установлен! Проверьте файл .env")