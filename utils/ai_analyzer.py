"""
Модуль для работы с нейросетью DeepSeek.
Генерирует аналитические сводки по результатам поиска.
"""
import logging
import aiohttp
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL

logger = logging.getLogger(__name__)


async def analyze_search_results(
        search_type: str,
        search_value: str,
        results: list
) -> str:
    """
    Генерирует AI-анализ результатов поиска.

    Args:
        search_type: Тип поиска ('fio', 'phone')
        search_value: Значение запроса
        results: Список найденных организаций

    Returns:
        Текст аналитической сводки или сообщение об ошибке
    """
    if not DEEPSEEK_API_KEY:
        return "⚠️ AI-анализ недоступен: не настроен API-ключ DeepSeek"

    if not results:
        return "📭 Нет данных для анализа"

    try:
        # 1. - Агрегация данных в компактную сводку
        summary = _aggregate_results(search_type, search_value, results)

        # 2. - Формирование промпта для нейросети
        prompt = _build_prompt(search_type, search_value, summary)

        # 3. - Отправка запроса к DeepSeek
        response_text = await _call_deepseek(prompt)

        return response_text

    except Exception as e:
        logger.error(f"Ошибка AI-анализа: {e}", exc_info=True)
        return f"⚠️ Не удалось выполнить AI-анализ: {str(e)}"


def _aggregate_results(search_type: str, search_value: str, results: list) -> str:
    """
    Агрегирует результаты в компактную текстовую сводку.
    Это решает проблему с большим числом организаций.
    """
    total = len(results)

    # Подсчёт статусов
    statuses = {}
    for r in results:
        status = r.get('status', 'Неизвестно')
        statuses[status] = statuses.get(status, 0) + 1

    # Подсчёт типов организаций
    types = {}
    for r in results:
        org_type = r.get('type', 'Не определено')
        types[org_type] = types.get(org_type, 0) + 1

    # Топ-10 организаций (первые из списка)
    top_orgs = results[:10]

    # Формирование текстовой сводки
    lines = [
        f"ЗАПРОС: {search_value}",
        f"ТИП ПОИСКА: {'ФИО' if search_type == 'fio' else 'Телефон'}",
        f"ВСЕГО НАЙДЕНО: {total}",
        "",
        "СТАТУСЫ:",
    ]

    for status, count in sorted(statuses.items(), key=lambda x: -x[1]):
        lines.append(f"- {status}: {count}")

    lines.append("")
    lines.append("ТИПЫ ОРГАНИЗАЦИЙ:")
    for org_type, count in sorted(types.items(), key=lambda x: -x[1]):
        lines.append(f"- {org_type}: {count}")

    lines.append("")
    lines.append("ПЕРВЫЕ 10 ОРГАНИЗАЦИЙ (детали):")
    for i, org in enumerate(top_orgs, 1):
        lines.append(
            f"{i}. {org.get('name', 'Без названия')} | "
            f"ИНН: {org.get('inn', '—')} | "
            f"Статус: {org.get('status', '—')} | "
            f"Адрес: {org.get('address', '—')[:60]}"
        )

    return "\n".join(lines)


def _build_prompt(search_type: str, search_value: str, summary: str) -> str:
    """Формирует промпт для нейросети."""

    search_type_text = "ФИО человека" if search_type == 'fio' else "номер телефона"

    return f"""Ты — аналитик службы безопасности. Проанализируй данные из реестра ФНС России (ЕГРЮЛ/ЕГРИП), найденные по запросу "{search_value}" ({search_type_text}).

ДАННЫЕ:
{summary}

ЗАДАЧА:
Составь краткую аналитическую сводку на русском языке. Структура ответа:

1. **Общий вывод** (1-2 предложения) — что можно сказать о результатах в целом
2. **Ключевые факты** (3-5 пунктов) — самые важные наблюдения
3. **Факторы внимания** (если есть) — что может быть подозрительным или требовать проверки

ТРЕБОВАНИЯ:
- Ответ должен быть кратким (не более 150 слов)
- Используй деловой стиль
- Не выдумывай фактов, которых нет в данных
- Если данных мало — так и скажи
- Не используй markdown-заголовки, только простые пункты с эмодзи
"""


async def _call_deepseek(prompt: str) -> str:
    """Отправляет запрос к API DeepSeek используя requests (лучше работает с VPN)."""
    import requests

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 8000
    }

    try:
        # requests отдельным потоком (блокался asyncio, ругался)
        import asyncio
        loop = asyncio.get_event_loop()

        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                DEEPSEEK_API_URL,
                headers=headers,
                json=payload,
                timeout=60
            )
        )

        if response.status_code != 200:
            logger.error(f"DeepSeek API ошибка {response.status_code}: {response.text}")
            return f"⚠️ Ошибка API DeepSeek (код {response.status_code})"

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()

    except requests.exceptions.ConnectionError as e:
        logger.error(f"Ошибка подключения к DeepSeek: {e}")
        return "⚠️ Не удалось подключиться к DeepSeek API. Проверьте VPN/прокси."
    except Exception as e:
        logger.error(f"Неожиданная ошибка при запросе к DeepSeek: {e}", exc_info=True)
        return f"⚠️ Ошибка при запросе к DeepSeek: {str(e)}"


# ==========================================
# Тестовая функция для проверки работоспособности
# ==========================================
async def test_deepseek_connection() -> str:
    """Простой тест подключения к DeepSeek."""
    try:
        result = await _call_deepseek("Напиши одно слово: работает")
        return f"✅ DeepSeek подключен! Ответ: {result}"
    except Exception as e:
        return f"❌ Ошибка подключения: {str(e)}"