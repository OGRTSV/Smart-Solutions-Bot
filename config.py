import os

BOT_TOKEN = '8811739946:AAGMWo2hrTywoVwMdSW6BCC1RaZol5g9tls'
SEARCH_COOLDOWN = 60  # секунд между поисками

# ==========================================
# GitHub API настройки
# ==========================================
GITHUB_API_URL = "https://api.github.com"
# Токен GitHub (опционально) - увеличивает лимит запросов с 60 до 5000 в час
# Создаётся на https://github.com/settings/tokens (нужен только read-only доступ)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", None)