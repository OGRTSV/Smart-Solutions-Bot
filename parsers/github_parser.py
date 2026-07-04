import aiohttp
import logging
from config import GITHUB_API_URL, GITHUB_TOKEN

logger = logging.getLogger(__name__)


def _get_headers():
    """Формирует заголовки для запросов к GitHub API."""
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


async def get_user(username: str) -> dict | None:
    """
    Получает информацию о пользователе GitHub по никнейму.

    Args:
        username: Никнейм пользователя на GitHub

    Returns:
        dict с данными пользователя или None, если не найден
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API_URL}/users/{username}"
            async with session.get(url, headers=_get_headers()) as response:
                if response.status == 404:
                    logger.info(f"Пользователь GitHub {username} не найден")
                    return None
                if response.status != 200:
                    logger.warning(f"Ошибка GitHub API для {username}: статус {response.status}")
                    return None
                return await response.json()
    except Exception as e:
        logger.error(f"Ошибка при получении профиля GitHub {username}: {e}")
        return None


async def get_repos(username: str) -> list:
    """
    Получает список репозиториев пользователя.

    Args:
        username: Никнейм пользователя

    Returns:
        list с данными репозиториев (до 100 штук, отсортированы по обновлению)
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API_URL}/users/{username}/repos?per_page=100&sort=updated"
            async with session.get(url, headers=_get_headers()) as response:
                if response.status != 200:
                    logger.warning(f"Ошибка получения репозиториев {username}: статус {response.status}")
                    return []
                return await response.json()
    except Exception as e:
        logger.error(f"Ошибка при получении репозиториев {username}: {e}")
        return []


async def get_user_events(username: str) -> list:
    """
    Получает последнюю публичную активность пользователя.

    Args:
        username: Никнейм пользователя

    Returns:
        list с событиями активности (до 30 штук)
    """
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{GITHUB_API_URL}/users/{username}/events/public?per_page=30"
            async with session.get(url, headers=_get_headers()) as response:
                if response.status != 200:
                    logger.warning(f"Ошибка получения активности {username}: статус {response.status}")
                    return []
                return await response.json()
    except Exception as e:
        logger.error(f"Ошибка при получении активности {username}: {e}")
        return []


def analyze_repos(repos: list) -> dict:
    """
    Анализирует репозитории пользователя и возвращает статистику.

    Args:
        repos: Список репозиториев от GitHub API

    Returns:
        dict со статистикой: языки, звёзды, форки, топики, топ-репозитории
    """
    if not repos:
        return {}

    languages = {}
    total_stars = 0
    total_forks = 0
    topics_all = []

    for repo in repos:
        # Пропускаем форки
        if repo.get("fork"):
            continue

        # Считаем языки
        lang = repo.get("language")
        if lang:
            languages[lang] = languages.get(lang, 0) + 1

        # Считаем звёзды и форки
        total_stars += repo.get("stargazers_count", 0)
        total_forks += repo.get("forks_count", 0)

        # Собираем топики
        topics_all.extend(repo.get("topics", []))

    # Топ-5 языков
    top_langs = sorted(languages.items(), key=lambda x: x[1], reverse=True)[:5]

    # Топ-10 уникальных топиков
    top_topics = list(dict.fromkeys(topics_all))[:10]

    # Топ-5 репозиториев по звёздам (только оригинальные)
    top_repos = sorted(
        [r for r in repos if not r.get("fork")],
        key=lambda x: x.get("stargazers_count", 0),
        reverse=True
    )[:5]

    return {
        "languages": top_langs,
        "total_stars": total_stars,
        "total_forks": total_forks,
        "topics": top_topics,
        "top_repos": top_repos,
        "original_count": len([r for r in repos if not r.get("fork")]),
        "fork_count": len([r for r in repos if r.get("fork")]),
    }


def analyze_activity(events: list) -> dict:
    """
    Анализирует активность пользователя и возвращает статистику по типам событий.

    Args:
        events: Список событий от GitHub API

    Returns:
        dict с количеством событий по типам (отсортировано по убыванию)
    """
    if not events:
        return {}

    event_types = {}
    for event in events:
        event_type = event.get("type", "Other")
        event_types[event_type] = event_types.get(event_type, 0) + 1

    # Преобразуем технические названия в читаемые
    readable_names = {
        "PushEvent": "🔨 Коммиты",
        "PullRequestEvent": "🔀 Pull Requests",
        "IssuesEvent": "🐛 Issues",
        "WatchEvent": "⭐ Starred репозитории",
        "ForkEvent": "🍴 Форки",
        "CreateEvent": "🆕 Создание веток/тегов",
        "IssueCommentEvent": "💬 Комментарии",
        "ReleaseEvent": "📦 Релизы",
    }

    result = {}
    for event_type, count in event_types.items():
        label = readable_names.get(event_type, event_type)
        result[label] = count

    # Сортируем по убыванию
    return dict(sorted(result.items(), key=lambda x: x[1], reverse=True))


async def search_github(username: str) -> dict:
    """
    Основная функция поиска по GitHub. Получает профиль и базовую статистику.

    Args:
        username: Никнейм пользователя на GitHub

    Returns:
        dict с результатом поиска:
        {
            "found": True/False,
            "user": {...},           # данные профиля
            "repos_stats": {...},    # статистика репозиториев
            "error": "..."           # сообщение об ошибке (если есть)
        }
    """
    try:
        # Получаем профиль
        user = await get_user(username)

        if not user:
            return {
                "found": False,
                "user": None,
                "repos_stats": None,
                "error": f"Пользователь `{username}` не найден на GitHub"
            }

        # Получаем репозитории и анализируем их
        repos = await get_repos(username)
        repos_stats = analyze_repos(repos)

        logger.info(f"GitHub профиль {username} получен успешно")

        return {
            "found": True,
            "user": user,
            "repos_stats": repos_stats,
            "error": None
        }

    except Exception as e:
        logger.error(f"Критическая ошибка при поиске GitHub {username}: {e}")
        return {
            "found": False,
            "user": None,
            "repos_stats": None,
            "error": f"Ошибка при обращении к GitHub API: {str(e)}"
        }