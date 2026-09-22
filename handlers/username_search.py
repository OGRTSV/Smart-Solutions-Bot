import asyncio
import os
import time
import logging
from datetime import datetime
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from states import SearchStates
from config import SEARCH_COOLDOWN
from utils.validators import validate_username
from utils.keyboards import get_main_keyboard, get_cancel_keyboard
from utils.excel_generator import create_excel_file_username
from parsers.username_parser import search_username
from core import bot, user_last_search, cancel_events, pending_cache_queries

from utils.ai_analyzer import analyze_search_results, ai_answer_query

from utils.database import (
    get_or_create_user,
    create_request,
    update_request_success,
    update_request_error,
    check_cache,
    save_to_cache,
    get_cache_date
)

router = Router()

# Хранилище последних результатов для AI-анализа (user_id -> данные)
# Переиспользуем общее хранилище из fio_search.py
from handlers.fio_search import ai_analysis_data


@router.message(SearchStates.waiting_for_username, lambda message: message.text and not message.text.startswith('/'))
async def process_username_input(message: types.Message, state: FSMContext):
    """Обработчик ввода username для поиска по платформам."""

    print(f"🔍 [DEBUG] process_username_input вызвана! Текст: '{message.text}'")
    print(f"🔍 [DEBUG] Состояние FSM: {await state.get_state()}")

    user_id = message.from_user.id
    now = asyncio.get_event_loop().time()

    # Проверка на спам
    if user_id in user_last_search and now - user_last_search[user_id] < SEARCH_COOLDOWN:
        remaining = int(SEARCH_COOLDOWN - (now - user_last_search[user_id]))
        await message.answer(f"⏳ Пожалуйста, подождите {remaining} сек. между поисками.")
        return

    # Валидация
    username = message.text.strip()
    if not validate_username(username):
        await message.answer(
            "❌ Неверный формат username.\n\n"
            "Допускаются: латинские буквы, цифры, символы `.` `_` `-`\n"
            "Длина: от 3 до 30 символов\n"
            "Ник не может состоять только из цифр.\n"
            "Примеры: john_doe, user123, my.profile"
        )
        return

    # Таймер ставим ТОЛЬКО после успешной валидации
    user_last_search[user_id] = now

    # Удаляем сообщение-запрос
    data = await state.get_data()
    username_msg_id = data.get('username_request_msg_id')
    chat_id = data.get('chat_id')
    if username_msg_id and chat_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=username_msg_id)
        except Exception as e:
            logging.error(f"Не удалось удалить сообщение с запросом username: {e}")

    # Удаляем сообщение пользователя
    try:
        await message.delete()
    except Exception:
        pass

    # ID пользователя из БД
    user_db_id = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    # ============================================================
    # ПРОВЕРКА КЭША
    # ============================================================
    cached_results = check_cache('username', username, 'multiplatform')

    if cached_results:
        cache_date = get_cache_date('username', username, 'multiplatform')
        days_ago = (datetime.now() - datetime.strptime(cache_date, '%Y-%m-%d')).days

        pending_cache_queries[user_id] = {
            "search_type": "username",
            "search_value": username,
            "source": "multiplatform"
        }

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Быстрый ответ (из кэша)",
                    callback_data=f"cq_username_quick_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Новый поиск (актуальные данные)",
                    callback_data=f"cq_username_new_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🏠 В меню",
                    callback_data="back_to_menu"
                )
            ]
        ])

        await message.answer(
            f"✅ *Username:* `{username}` уже найден в базе данных\n"
            f"📅 Дата последнего обновления: *{cache_date}* ({days_ago} дн. назад)\n"
            f"🌐 Найдено профилей: *{len(cached_results)}*\n\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return

    # ============================================================
    # КЭША НЕТ — запускаем полноценный поиск
    # ============================================================
    await message.answer(f"✅ *Username принят:* `{username}`", parse_mode="Markdown")

    await state.set_state(SearchStates.searching)
    cancel_event = asyncio.Event()
    cancel_events[user_id] = cancel_event

    loading_msg = await message.answer(
        "⏳ *Идёт поиск username по платформам...*\n\n"
        "Бот проверяет наличие этого ника на множестве сайтов (GitHub, VK, Telegram и др.).\n\n"
        "Пожалуйста, подождите. Это может занять 1-2 минуты.\n\n"
        "Вы можете отменить поиск в любой момент.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )

    request_id = create_request(user_db_id, 'username', username, 'multiplatform')
    start_time = time.time()

    result = await search_username(username, cancel_event)
    execution_time_ms = int((time.time() - start_time) * 1000)

    if result.get("cancelled"):
        update_request_error(request_id, 'cancelled', 'Отменено пользователем')
        cancel_events.pop(user_id, None)
        await state.clear()
        return

    try:
        await loading_msg.delete()
    except Exception:
        pass

    cancel_events.pop(user_id, None)
    await state.clear()

    if "error" in result:
        update_request_error(request_id, 'parser_error', result['error'])
        await message.answer(f"❌ Ошибка: {result['error']}", reply_markup=get_main_keyboard())
        return

    if not result.get("found"):
        update_request_success(request_id, [], execution_time_ms)

        # Сохраняем пустые результаты для AI-вопроса
        ai_analysis_data[user_id] = {
            "search_type": "username",
            "search_value": username,
            "results": []
        }

        await message.answer(
            f"*По username: {username}*\n\n"
            f"🌐 Профилей не найдено\n"
            f"🔹 Проверено сайтов: *{result['checked']}*\n"
            f"🔹 Возможно, этот ник не используется или используется редко.\n"
            f"🔹 Иногда при поиске возникают ошибки и результат не показывается. Попробуйте повторить поиск.\n"
            f"🔹 Вы можете задать вопрос нейросети по кнопке ниже.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
            ])
        )
        return

    # Успешный поиск
    update_request_success(request_id, result['results'], execution_time_ms)
    save_to_cache('username', username, 'multiplatform', result['results'])

    # Сохраняем результаты для AI-анализа
    ai_analysis_data[user_id] = {
        "search_type": "username",
        "search_value": username,
        "results": result['results']
    }

    await _show_username_results(message, username, result)


async def _show_username_results(message: types.Message, username: str, result: dict):
    """Показывает результаты поиска по username (Excel + AI-кнопки)."""
    await message.answer(
        f"🌐 *Найдено профилей: {result['count']}* из {result['checked']} проверенных сайтов. "
        f"Формирую Excel-файл...",
        parse_mode="Markdown"
    )

    filepath = create_excel_file_username(username, result['results'])

    caption_text = (
        f"📁 *Результаты поиска по username: {username}*\n"
        f"🔹 Найдено профилей: *{result['count']}*\n"
        f"🔹 Проверено сайтов: *{result['checked']}*\n"
        f"🔹 Ошибок проверки: *{result['errors']}*"
        f"\n⚠️ _Внимание: некоторые ссылки могут быть неточными (ложные срабатывания). Рекомендуем проверять ключевые профили вручную._"
    )

    await bot.send_chat_action(chat_id=message.chat.id, action="upload_document")
    await message.answer_document(
        document=FSInputFile(filepath),
        caption=caption_text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 AI-анализ профилей", callback_data="ai_analyze_username")],
            [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
        ])
    )

    try:
        os.remove(filepath)
    except Exception as e:
        logging.error(f"Не удалось удалить файл: {e}")


# ==========================================
# ИИ-АНАЛИЗ: Анализ найденных профилей
# ==========================================
@router.callback_query(F.data == "ai_analyze_username")
async def handle_ai_analyze_username(callback: types.CallbackQuery):
    """Обработчик кнопки AI-анализа для поиска по username."""
    await callback.answer("🤖 Запускаю AI-анализ профилей...")

    user_id = callback.from_user.id
    data = ai_analysis_data.get(user_id)

    if not data:
        await callback.message.answer(
            "⚠️ Нет данных для анализа. Выполните поиск заново.",
            reply_markup=get_main_keyboard()
        )
        return

    loading_msg = await callback.message.answer(
        "⏳ Нейросеть анализирует найденные профили...\n"
        "Это может занять до минуты."
    )

    # Вызов нейросети
    analysis = await analyze_search_results(
        data["search_type"],
        data["search_value"],
        data["results"]
    )

    response_text = (
        f"🤖 AI-анализ профилей для username: {data['search_value']}\n\n"
        f"{analysis}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Анализ выполнен с помощью нейросети. Рекомендуется проверять важную информацию."
    )

    if len(response_text) > 4096:
        response_text = response_text[:4090] + "…"

    await loading_msg.edit_text(response_text)