"""
Парсер для поиска username по множеству платформ.

Идея взята из проекта Blackbird (OSINT): проверка существования аккаунта
на множестве сайтов через HTTP-запросы. В отличие от Blackbird (CLI, синхронный),
реализовано асинхронно (aiohttp) с ограничением параллельных запросов.

База сайтов лежит в data/username_sites.json — сайты можно добавлять
и убирать без правки кода.
"""
import asyncio
import json
import logging
import os
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Путь к базе сайтов (папка data в корне проекта)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITES_PATH = os.path.join(PROJECT_ROOT, "data", "username_sites.json")

# User-Agent как у браузера, чтобы сайты не отклоняли нас как бота
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Сколько сайтов проверяем параллельно (больше = быстрее, но риск бана IP)
MAX_CONCURRENT = 10

# Таймаут одного запроса, сек
REQUEST_TIMEOUT = 12


def load_sites() -> list:
    """Загружает базу сайтов из JSON."""
    if not os.path.exists(SITES_PATH):
        logger.error(f"❌ База сайтов не найдена: {SITES_PATH}")
        return []

    with open(SITES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("sites", [])


async def _check_site(
        session: aiohttp.ClientSession,
        site: dict,
        username: str,
        semaphore: asyncio.Semaphore
) -> dict:
    """Проверяет один сайт на наличие аккаунта с данным username."""
    url = site["url"].format(username=username)
    result = {
        "site": site["name"],
        "url": url,
        "category": site.get("category", "Другое"),
        "found": False,
        "error": None,
    }

    async with semaphore:
        try:
            async with session.get(url) as resp:
                status = resp.status
                check = site.get("check", "status")

                if check == "status":
                    # Простой способ: 200 = аккаунт есть, 404 = нет
                    result["found"] = (status == 200)

                elif check == "marker":
                    # Точный способ: ищем маркеры в HTML страницы
                    if status == 200:
                        text = await resp.text()

                        absent = site.get("absent_marker")
                        present = site.get("exists_marker")

                        if absent and absent in text:
                            result["found"] = False
                        elif present:
                            result["found"] = present in text
                        else:
                            result["found"] = True
                    else:
                        result["found"] = False

        except asyncio.TimeoutError:
            result["error"] = "timeout"
        except aiohttp.ClientError as e:
            result["error"] = f"client_error: {type(e).__name__}"
        except Exception as e:
            result["error"] = str(e)

    return result


async def search_username(
        username: str,
        cancel_event: Optional[asyncio.Event] = None
) -> dict:
    """
    Проверяет наличие username на всех сайтах из базы.

    Returns:
        dict с ключами:
        - found: bool — найден ли хотя бы один профиль
        - count: количество найденных профилей
        - checked: сколько сайтов проверено
        - results: список найденных {site, url, category}
        - errors: количество сайтов с ошибками (таймауты, блокировки)
    """
    sites = load_sites()

    if not sites:
        return {
            "found": False, "count": 0, "checked": 0,
            "results": [], "errors": 0,
            "error": "База сайтов пуста или не найдена"
        }

    logger.info(f"🔍 Начинаю поиск username '{username}' по {len(sites)} сайтам")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    headers = {"User-Agent": USER_AGENT}
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)

    found_results = []
    errors_count = 0
    checked = 0

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        tasks = [_check_site(session, site, username, semaphore) for site in sites]

        for coro in asyncio.as_completed(tasks):
            res = await coro
            checked += 1

            # Поддержка отмены поиска
            if cancel_event and cancel_event.is_set():
                logger.info("❌ Поиск по username отменён пользователем")
                return {
                    "cancelled": True, "found": False,
                    "count": len(found_results), "checked": checked,
                    "results": found_results, "errors": errors_count
                }

            if res["error"]:
                errors_count += 1
            elif res["found"]:
                found_results.append(res)
                logger.info(f"✅ Найден профиль: {res['site']} → {res['url']}")

    # Сортируем по названию сайта для стабильной выдачи
    found_results.sort(key=lambda r: r["site"])

    logger.info(
        f"🏁 Поиск по username завершён: найдено {len(found_results)} "
        f"из {checked} проверенных, ошибок: {errors_count}"
    )

    return {
        "found": len(found_results) > 0,
        "count": len(found_results),
        "checked": checked,
        "results": found_results,
        "errors": errors_count,
    }