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
from utils.validators import validate_phone
from utils.keyboards import get_main_keyboard, get_cancel_keyboard
from utils.excel_generator import create_excel_file_phone
from parsers.phone_parser import search_phone_org
from core import bot, user_last_search, cancel_events, pending_cache_queries

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

@router.message(SearchStates.waiting_for_phone, lambda message: message.text and not message.text.startswith('/'))
async def process_phone_input(message: types.Message, state: FSMContext):
    """Обработчик ввода номера телефона для поиска организаций."""

    # ОТЛАДКА
    print(f"🔍 [DEBUG] process_phone_input вызвана! Текст: '{message.text}'")
    print(f"🔍 [DEBUG] Состояние FSM: {await state.get_state()}")

    user_id = message.from_user.id
    now = asyncio.get_event_loop().time()

    # Проверка на спам
    if user_id in user_last_search and now - user_last_search[user_id] < SEARCH_COOLDOWN:
        remaining = int(SEARCH_COOLDOWN - (now - user_last_search[user_id]))
        await message.answer(f"⏳ Пожалуйста, подождите {remaining} сек. между поисками.")
        return

    user_last_search[user_id] = now

    # Валидация
    valid_phone = validate_phone(message.text)
    if not valid_phone:
        await message.answer("❌ Неверный формат номера. Пожалуйста, введите корректный российский номер (11 цифр).")
        return

    # Удаляем сообщение-запрос
    data = await state.get_data()
    phone_msg_id = data.get('phone_request_msg_id')
    chat_id = data.get('chat_id')
    if phone_msg_id and chat_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=phone_msg_id)
        except Exception as e:
            logging.error(f"Не удалось удалить сообщение с запросом телефона: {e}")

    # Удаляем сообщение пользователя с введённым номером
    try:
        await message.delete()
    except Exception:
        pass

    # Получаем ID пользователя из БД
    user_db_id = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    # ============================================================
    # ПРОВЕРКА КЭША
    # ============================================================
    cached_results = check_cache('phone', valid_phone, 'listorg')

    if cached_results:
        cache_date = get_cache_date('phone', valid_phone, 'listorg')
        days_ago = (datetime.now() - datetime.strptime(cache_date, '%Y-%m-%d')).days

        # Сохраняем данные запроса во временный словарь
        pending_cache_queries[user_id] = {
            "search_type": "phone",
            "search_value": valid_phone,
            "source": "listorg"
        }

        # Короткие callback_data
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Быстрый ответ (из кэша)",
                    callback_data=f"cq_phone_quick_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Новый поиск (актуальные данные)",
                    callback_data=f"cq_phone_new_{user_id}"
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
            f"✅ *Номер:* `{valid_phone}` уже найден в базе данных\n"
            f"📅 Дата последнего обновления: *{cache_date}* ({days_ago} дн. назад)\n"
            f"🏢 Найдено организаций: *{len(cached_results)}*\n\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return  # Выходим, дальше обработают callback'и

    # ============================================================
    # КЭША НЕТ — запускаем полноценный поиск
    # ============================================================
    await message.answer(f"✅ Номер принят: `{valid_phone}`", parse_mode="Markdown")

    await state.set_state(SearchStates.searching)
    cancel_event = asyncio.Event()
    cancel_events[user_id] = cancel_event

    loading_msg = await message.answer(
        "⏳ *Идёт поиск организаций по номеру телефона...*\n\n"
        "Пожалуйста, подождите. Это может занять несколько минут.\n\n"
        "Вы можете отменить поиск в любой момент.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )

    request_id = create_request(user_db_id, 'phone', valid_phone, 'listorg')
    start_time = time.time()

    result = await search_phone_org(valid_phone, cancel_event)
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
        await message.answer(
            f"*По номеру: {valid_phone}*\n"
            f"🔹 Организаций не найдено\n"
            f"🔹 Возможно, номер не зарегистрирован на юридическое лицо.",
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown"
        )
        return

    update_request_success(request_id, result['results'], execution_time_ms)
    save_to_cache('phone', valid_phone, 'listorg', result['results'])

    # ==========================================
    # Формирование и отправка Excel
    # ==========================================
    await message.answer(
        f"📊 *Найдено организаций: {result['count']}*. Формирую Excel-файл...",
        parse_mode="Markdown"
    )

    filepath = create_excel_file_phone(valid_phone, result['results'])

    caption_text = (
        f"📁 *Результаты поиска по телефону: {valid_phone}*\n"
        f"🔹 Найдено организаций: *{result['count']}*\n"
        f"🔹 Источник: list-org.com"
    )

    await bot.send_chat_action(chat_id=message.chat.id, action="upload_document")
    await message.answer_document(
        document=FSInputFile(filepath),
        caption=caption_text,
        parse_mode="Markdown"
    )

    await message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())

    try:
        os.remove(filepath)
    except Exception as e:
        logging.error(f"Не удалось удалить файл: {e}")