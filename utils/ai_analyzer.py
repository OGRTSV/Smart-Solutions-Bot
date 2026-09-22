"""
Модуль для работы с нейросетью DeepSeek.

Два режима работы:
1. Chat Completions API — анализ результатов парсинга (ФИО, телефон, username)
   Модель: deepseek-v4-flash (быстрая, дешёвая)

2. Responses API — свободный веб-поиск с встроенным web_search
   Модель: deepseek-v4-pro (глубокое мышление, идеально для OSINT)
   DeepSeek сам решает, когда искать в интернете, и сам выполняет поиск.

Версия: 3.1 (поддержка username-поиска)
"""
import logging
import asyncio
from openai import AsyncOpenAI

import config

logger = logging.getLogger(__name__)

# Маркер, что файл обновлён
logger.info("🚀 AI-анализатор загружен (DeepSeek Chat + Responses API, +username)")


# ============================================================================
# 1. АНАЛИЗ РЕЗУЛЬТАТОВ ПАРСИНГА (Chat Completions API)
# ============================================================================
async def analyze_search_results(
        search_type: str,
        search_value: str,
        results: list
) -> str:
    """
    Генерирует AI-анализ результатов поиска.
    Поддерживает: fio, phone, username.
    """
    if not config.DEEPSEEK_API_KEY:
        return "⚠️ AI-анализ недоступен: не настроен API-ключ DeepSeek"

    if not results:
        return "📭 Нет данных для анализа"

    try:
        summary = _aggregate_results(search_type, search_value, results)
        prompt = _build_prompt(search_type, search_value, summary)
        response_text = await _call_deepseek_chat(prompt)
        return response_text

    except Exception as e:
        logger.error(f"Ошибка AI-анализа: {e}", exc_info=True)
        return f"⚠️ Не удалось выполнить AI-анализ: {str(e)}"


# ============================================================================
# 2. СВОБОДНЫЙ AI-ПОИСК (Responses API с web_search)
# ============================================================================
async def ai_answer_query(
        user_query: str,
        search_type: str,
        search_value: str,
        results: list
) -> str:
    """
    Отвечает на свободный вопрос пользователя через DeepSeek с встроенным веб-поиском.
    Использует Responses API — модель сама решает, когда искать в интернете.
    Пользователь может формулировать вопрос как угодно.
    """
    logger.info(f"🌐 AI-ПОИСК ВЫЗВАН через DeepSeek Responses API")
    logger.info(f"   DEEPSEEK_API_KEY: {'✅ есть' if config.DEEPSEEK_API_KEY else '❌ НЕТ'}")
    logger.info(f"   Модель: {config.DEEPSEEK_RESPONSES_MODEL}")
    logger.info(f"   Тип поиска: {search_type}")

    if not config.DEEPSEEK_API_KEY:
        return "⚠️ AI-поиск недоступен: не настроен API-ключ DeepSeek"

    try:
        # Формируем контекст из результатов предыдущего поиска
        context = _build_context_for_ai(search_type, search_value, results)

        # Системный промпт — универсальный поисковый ассистент
        system_prompt = """Ты — универсальный поисковый аналитический ассистент по открытым источникам (OSINT). Ты не просто находишь информацию, но и анализируешь её: сопоставляешь факты из разных источников, оцениваешь их надёжность и делаешь обоснованные выводы. Ты помогаешь находить любую публичную информацию о людях и организациях: новости, упоминания в СМИ, профессиональную деятельность, соцсети, интервью, судебные дела и любые другие публичные следы.

ПРАВИЛА РАБОТЫ:
1. Используй веб-поиск для получения актуальной информации.
2. Отвечай на русском языке.
3. Данные из контекста — это ОТПРАВНАЯ ТОЧКА и набор идентификаторов (ФИО, ИНН, username, регион, связанные компании и профили). Используй их, чтобы понимать, о ком речь, и отличать нужного человека/организацию от тёзок и однофамильцев, но НЕ ограничивай поиск только этими данными.
4. Ищи разносторонне: СМИ и новости, профессиональные площадки и публикации, соцсети и публичные профили, интервью и подкасты, судебные дела и исполнительные производства, отзывы и упоминания в сообществах.
5. Адаптируйся под вопрос: если вопрос узкий — отвечай именно на него; если общий ("расскажи всё") — составь разносторонний портрет, начиная с самого значимого.
6. Давай структурированные ответы с фактами и цифрами. Деловой стиль, без markdown-заголовков, можно использовать простые пункты с эмодзи.
7. Не выдумывай факты. Если по какому-то направлению ничего не найдено — честно скажи об этом.
8. Сопоставляй информацию из разных источников. Если источники противоречат друг другу — укажи это явно и приведи обе версии со ссылками.
9. Отделяй подтверждённые факты от предположений. Если факт найден только в одном источнике или не подтверждён однозначно — помечай его как "вероятно" или "по данным одного источника".
10. В конце ответа ОБЯЗАТЕЛЬНО перечисли все использованные источники в формате:

📎 Источники:
• [Заголовок] — ссылка

11. Если запрос содержит неприемлемый, оскорбительный или противозаконный контент — ответь ТОЛЬКО фразой: "⚠️ Запрос некорректен. Я не могу на него ответить." и не выдавай никакой информации.

ПРОВЕРКА РЕЛЕВАНТНОСТИ (важно):
- Сверяй каждый источник с идентификаторами из контекста.
- Для поиска по ФИО/телефону: сверяй по точным ФИО + ИНН + регион + связанные компании.
- Для поиска по username: сверяй по точному написанию ника и платформам, на которых он найден.
- Источники про других людей (с другими ИНН, регионами или похожими, но другими никами) НЕ используй.
- Если уверенности, что источник про нужного человека, нет — помечай: "возможно, другой человек с тем же ФИО/ником".
- Если релевантных источников не найдено — честно напиши об этом и не перечисляй нерелевантные.
"""

        # Формируем user content: контекст как отправная точка, а не как тема поиска
        if context:
            if search_type == 'username':
                context_header = (
                    f"ОТПРАВНАЯ ТОЧКА — результаты поиска username по множеству платформ "
                    f"(используй как идентификаторы, чтобы понять, о ком речь, и не путать с одноимённиками):\n"
                )
            elif search_type == 'fio':
                context_header = (
                    f"ОТПРАВНАЯ ТОЧКА — данные поиска в реестрах ФНС "
                    f"(используй как идентификаторы, чтобы понять, о ком речь, и не путать с тёзками):\n"
                )
            elif search_type == 'phone':
                context_header = (
                    f"ОТПРАВНАЯ ТОЧКА — данные поиска организаций по номеру телефона в реестрах "
                    f"(используй как идентификаторы, чтобы понять, о каких организациях речь):\n"
                )
            else:
                context_header = f"ОТПРАВНАЯ ТОЧКА — данные предыдущего поиска:\n"

            user_content = (
                f"{context_header}"
                f"{context}\n\n"
                f"ВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{user_query}"
            )
        else:
            user_content = user_query

        # Вызываем DeepSeek через Responses API
        response_text = await _call_deepseek_responses(system_prompt, user_content)
        return response_text

    except Exception as e:
        logger.error(f"Ошибка AI-поиска: {e}", exc_info=True)
        return f"⚠️ Не удалось выполнить AI-поиск: {str(e)}"


# ============================================================================
# 3. ВЕРИФИКАЦИЯ ПРОФИЛЕЙ USERNAME (Responses API + web_search)
# ============================================================================
async def verify_username_profiles(username: str, profiles: list) -> list:
    """
    Верифицирует список профилей через DeepSeek с веб-поиском.
    Модель проверяет каждую ссылку и определяет, реальный ли там профиль.

    Args:
        username: Искомый username
        profiles: Список найденных профилей [{site, url, category}]

    Returns:
        Список верифицированных профилей (только те, которые реально существуют)
    """
    if not config.DEEPSEEK_API_KEY:
        logger.warning("⚠️ Верификация недоступна: не настроен API-ключ DeepSeek")
        return profiles  # Возвращаем все без верификации

    if not profiles:
        return []

    logger.info(f"🔍 Начинаю верификацию {len(profiles)} профилей для username '{username}'")

    client = AsyncOpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )

    verified_profiles = []

    # Системный промпт для верификации
    system_prompt = """Ты — верификатор профилей в социальных сетях. Твоя задача — проверить, существует ли реальный профиль пользователя по указанной ссылке.

ПРАВИЛА:
1. Зайди на указанную страницу и проанализируй её содержимое.
2. Определи, есть ли там реальный профиль пользователя или это страница ошибки/не найдено.
3. Ответь ТОЛЬКО одним из двух вариантов:
   - "EXISTS" — если профиль реально существует
   - "NOT_EXISTS" — если это страница ошибки, "user not found" или профиль не существует

ВАЖНО:
- Не давай длинных объяснений, только одно слово
- Если страница требует логина или показывает капчу — считай, что профиль существует (EXISTS)
- Если видишь явные признаки несуществующего профиля (404, "not found", "doesn't exist", "this page isn't available" и т.п.) — отвечай NOT_EXISTS
"""

    for profile in profiles:
        try:
            logger.info(f"🔎 Проверяю: {profile['site']} - {profile['url']}")

            user_content = f"""Username: {username}
Ссылка на профиль: {profile['url']}
Сайт: {profile['site']}

Проверь, существует ли этот профиль. В конце обязательно напиши EXISTS или NOT_EXISTS."""

            # Используем flash для экономии
            response = await client.responses.create(
                model="deepseek-v4-flash",  # Flash для верификации
                instructions=system_prompt,
                input=user_content,
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                temperature=0.1,  # Низкая температура для точности
                max_output_tokens=3000,
            )

            # Извлекаем текст с fallback (если output_text пустой)
            answer = response.output_text or ""
            if not answer:
                answer = _extract_text_from_output(response)
                logger.info(f"   output_text пустой, извлёк из output: '{answer[:100]}'")

            answer_clean = answer.strip().upper()
            logger.info(f"   Ответ DeepSeek: '{answer_clean[:100]}'")

            # Отбрасываем ТОЛЬКО при явном NOT_EXISTS
            if "NOT_EXISTS" in answer_clean:
                logger.info(f"   ❌ Профиль не существует: {profile['site']}")
            else:
                # EXISTS или непонятный ответ — оставляем
                verified_profiles.append(profile)
                logger.info(f"   ✅ Профиль подтверждён: {profile['site']}")

        except Exception as e:
            logger.error(f"   ⚠️ Ошибка верификации {profile['site']}: {e}")
            verified_profiles.append(profile)

        logger.info(
            f"✅ Верификация завершена: {len(verified_profiles)} из {len(profiles)} профилей подтверждены"
        )
        return verified_profiles

# ============================================================================
# ВЫЗОВ DEEPSEEK RESPONSES API (с встроенным web_search)
# ============================================================================
async def _call_deepseek_responses(system_prompt: str, user_content: str) -> str:
    """
    Отправляет запрос в DeepSeek через Responses API с встроенным веб-поиском.
    Модель сама решает, когда искать в интернете.
    """
    client = AsyncOpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
    )

    try:
        logger.info(f"🔍 Отправляю запрос в DeepSeek Responses API (модель: {config.DEEPSEEK_RESPONSES_MODEL})")

        # Увеличенный лимит токенов для сложных запросов
        response = await client.responses.create(
            model=config.DEEPSEEK_RESPONSES_MODEL,
            instructions=system_prompt,
            input=user_content,
            tools=[{"type": "web_search"}],
            tool_choice="auto",
            temperature=0.3,
            max_output_tokens=16000,  # ← БЫЛО 8000, увеличили в 2 раза
        )

        logger.info(f"📦 Полный ответ от DeepSeek: {response}")

        # Извлекаем текст ответа
        answer = response.output_text or ""

        # Пытаемся извлечь источники из annotations
        sources = _extract_sources_from_response(response)

        logger.info(
            f"✅ DeepSeek ответил. "
            f"Длина: {len(answer)} символов. "
            f"Источников в annotations: {len(sources)}"
        )

        # Если ответ пустой — пробуем извлечь из output напрямую
        if not answer and hasattr(response, "output"):
            logger.warning("⚠️ output_text пустой, пытаюсь извлечь из output")
            answer = _extract_text_from_output(response)
            logger.info(f"Извлечено из output: {len(answer)} символов")

        # Если всё ещё пустой — делаем повторный запрос с просьбой дать ответ
        if not answer:
            logger.warning("⚠️ Ответ пустой, делаю повторный запрос")
            retry_prompt = "Ты уже собрал информацию. Теперь дай финальный структурированный ответ на основе найденных данных."
            retry_response = await client.responses.create(
                model=config.DEEPSEEK_RESPONSES_MODEL,
                instructions=retry_prompt,
                input=user_content,
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                temperature=0.3,
                max_output_tokens=16000,
            )
            answer = retry_response.output_text or ""
            if not answer:
                answer = _extract_text_from_output(retry_response)
            logger.info(f"После повторного запроса: {len(answer)} символов")

        # Если в ответе нет источников, но мы их нашли — добавим вручную
        if sources and "📎 Источники" not in answer:
            sources_text = "\n\n📎 Источники:\n"
            for i, (title, url) in enumerate(sources[:10], 1):
                if title:
                    sources_text += f"• [{title}]({url})\n"
                else:
                    sources_text += f"• {url}\n"
            answer += sources_text

        return answer

    except Exception as e:
        logger.error(f"Ошибка при запросе к DeepSeek Responses API: {e}", exc_info=True)
        return f"⚠️ Ошибка при обращении к DeepSeek API: {str(e)}"


def _extract_text_from_output(response) -> str:
    """
    Извлекает текст из response.output, если output_text пустой.
    """
    text_parts = []

    try:
        if not hasattr(response, "output") or not response.output:
            return ""

        for output_item in response.output:
            if hasattr(output_item, "type"):
                if output_item.type == "message":
                    if hasattr(output_item, "content"):
                        for content_item in output_item.content:
                            if hasattr(content_item, "type") and content_item.type == "output_text":
                                if hasattr(content_item, "text"):
                                    text_parts.append(content_item.text)
    except Exception as e:
        logger.warning(f"Ошибка при извлечении текста из output: {e}")

    return "\n".join(text_parts)


def _extract_sources_from_response(response) -> list:
    """
    Извлекает источники из ответа DeepSeek через annotations.
    """
    sources = []

    try:
        if not hasattr(response, "output") or not response.output:
            return sources

        for output_item in response.output:
            if hasattr(output_item, "content"):
                for content_item in output_item.content:
                    if hasattr(content_item, "annotations"):
                        for annotation in content_item.annotations:
                            url = None
                            title = None

                            if hasattr(annotation, "url"):
                                url = annotation.url
                            if hasattr(annotation, "title"):
                                title = annotation.title

                            if hasattr(annotation, "type") and annotation.type == "url_citation":
                                if hasattr(annotation, "url_citation"):
                                    citation = annotation.url_citation
                                    if hasattr(citation, "url"):
                                        url = citation.url
                                    if hasattr(citation, "title"):
                                        title = citation.title

                            if url:
                                sources.append((title, url))
    except Exception as e:
        logger.warning(f"Не удалось извлечь источники: {e}")

    seen = set()
    unique_sources = []
    for title, url in sources:
        if url not in seen:
            seen.add(url)
            unique_sources.append((title, url))

    return unique_sources


# ============================================================================
# ВЫЗОВ DEEPSEEK CHAT COMPLETIONS API (для анализа результатов парсинга)
# ============================================================================
async def _call_deepseek_chat(prompt: str) -> str:
    """Отправляет запрос к API DeepSeek используя requests (старый Chat Completions API)."""
    import requests

    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "max_tokens": 8000
    }

    try:
        loop = asyncio.get_event_loop()

        response = await loop.run_in_executor(
            None,
            lambda: requests.post(
                config.DEEPSEEK_API_URL,
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


# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================
def _build_context_for_ai(search_type: str, search_value: str, results: list) -> str:
    """Формирует контекст из результатов предыдущего поиска."""
    if not search_value:
        return ""

    # Если результатов нет — передаём минимум информации о запросе
    if not results:
        type_names = {
            "fio": "ФИО человека",
            "phone": "номер телефона",
            "username": "username в интернете"
        }
        type_name = type_names.get(search_type, "запрос")
        return (
            f"ПОИСК ПО {type_name} '{search_value}' В РЕЕСТРАХ И БАЗАХ ДАННЫХ "
            f"НЕ ДАЛ РЕЗУЛЬТАТОВ. Это отправная точка — попробуй найти информацию "
            f"об этом {type_name} в открытых источниках интернета."
        )

    return _aggregate_results(search_type, search_value, results)


def _aggregate_results(search_type: str, search_value: str, results: list) -> str:
    """
    Агрегирует результаты в компактную текстовую сводку.
    Автоматически выбирает нужный формат в зависимости от типа поиска.
    """
    if search_type == 'username':
        return _aggregate_username_results(search_value, results)
    else:
        # fio, phone и любые другие — стандартная агрегация организаций
        return _aggregate_org_results(search_type, search_value, results)


def _aggregate_org_results(search_type: str, search_value: str, results: list) -> str:
    """Агрегирует результаты поиска организаций (ФИО, телефон)."""
    total = len(results)

    statuses = {}
    for r in results:
        status = r.get('status', 'Неизвестно')
        statuses[status] = statuses.get(status, 0) + 1

    types = {}
    for r in results:
        org_type = r.get('type', 'Не определено')
        types[org_type] = types.get(org_type, 0) + 1

    top_orgs = results[:10]

    lines = [
        f"ЗАПРОС: {search_value}",
        f"ТИП ПОИСКА: {search_type}",
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


def _aggregate_username_results(search_value: str, results: list) -> str:
    """Агрегирует результаты поиска по username в текстовую сводку."""
    total = len(results)

    # Подсчёт по категориям (Соцсети, Разработка, Видео и т.д.)
    categories = {}
    for r in results:
        cat = r.get('category', 'Другое')
        categories[cat] = categories.get(cat, 0) + 1

    lines = [
        f"USERNAME: {search_value}",
        f"ВСЕГО НАЙДЕНО ПРОФИЛЕЙ: {total}",
        "",
        "ПО КАТЕГОРИЯМ:",
    ]

    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        lines.append(f"- {cat}: {count}")

    lines.append("")
    lines.append("СПИСОК НАЙДЕННЫХ ПРОФИЛЕЙ:")
    for i, profile in enumerate(results, 1):
        lines.append(
            f"{i}. {profile.get('site', 'Без названия')} | "
            f"Категория: {profile.get('category', '—')} | "
            f"URL: {profile.get('url', '—')}"
        )

    return "\n".join(lines)


def _build_prompt(search_type: str, search_value: str, summary: str) -> str:
    """
    Формирует промпт для нейросети DeepSeek (анализ результатов парсинга).
    Выбирает нужный промпт в зависимости от типа поиска.
    """
    if search_type == 'username':
        return f"""Ты — аналитик цифровой активности. Проанализируй найденные профили пользователя с username "{search_value}".

ДАННЫЕ:
{summary}

ЗАДАЧА:
Составь портрет пользователя на основе найденных профилей. Структура ответа:

1. **Общий вывод** (1-2 предложения) — что можно сказать о пользователе в целом
2. **Сферы активности** — где и чем занимается (разработка, творчество, соцсети, игры и т.д.)
3. **Ключевые наблюдения** — интересные факты из профилей, стилистика, интересы
4. **Потенциальные связи** — как профили могут быть связаны между собой

ТРЕБОВАНИЯ:
- Ответ должен быть кратким (не более 200 слов)
- Используй деловой стиль
- Не выдумывай фактов, которых нет в данных
- Если данных мало — так и скажи
- ВАЖНО: один и тот же username может использоваться разными людьми. Не утверждай категорично, что все профили принадлежат одному человеку — используй формулировки "вероятно", "возможно" или прямо указывай на неопределённость
- Не используй markdown-заголовки, только простые пункты с эмодзи
"""

    # Стандартный промпт для ФИО и телефона
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


# ============================================================================
# ТЕСТОВЫЕ ФУНКЦИИ
# ============================================================================
async def test_deepseek_connection() -> str:
    """Тест подключения к DeepSeek Chat Completions API."""
    try:
        result = await _call_deepseek_chat("Напиши одно слово: работает")
        return f"✅ DeepSeek (Chat API) подключен! Ответ: {result}"
    except Exception as e:
        return f"❌ Ошибка подключения: {str(e)}"


async def test_deepseek_responses() -> str:
    """Тест подключения к DeepSeek Responses API с веб-поиском."""
    try:
        result = await _call_deepseek_responses(
            "Ты helpful assistant.",
            "Напиши одно слово: работает"
        )
        return f"✅ DeepSeek (Responses API) подключен! Ответ: {result}"
    except Exception as e:
        return f"❌ Ошибка подключения к Responses API: {str(e)}"