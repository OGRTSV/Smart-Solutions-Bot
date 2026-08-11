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
from utils.validators import validate_fio
from utils.keyboards import get_main_keyboard, get_cancel_keyboard
from utils.excel_generator import create_excel_file_fns
from parsers.fns_parser import search_fns
from core import bot, user_last_search, cancel_events, pending_cache_queries
from utils.ai_analyzer import analyze_search_results

# Импорты для работы с базой данных
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
ai_analysis_data = {}


@router.message(SearchStates.waiting_for_fns, lambda message: message.text and not message.text.startswith('/'))
async def process_fns_input(message: types.Message, state: FSMContext):
    """Обработчик ввода ФИО для поиска в ФНС (ЕГРЮЛ/ЕГРИП)."""

    # ОТЛАДКА: проверяем, вызывается ли функция. Просто для удостоверенности
    print(f"🔍 [DEBUG] process_fns_input вызвана! Текст: '{message.text}'")
    print(f"🔍 [DEBUG] Состояние FSM: {await state.get_state()}")

    user_id = message.from_user.id
    now = asyncio.get_event_loop().time()

    # Проверка на спам (кулдаун 60 секунд)
    if user_id in user_last_search and now - user_last_search[user_id] < SEARCH_COOLDOWN:
        remaining = int(SEARCH_COOLDOWN - (now - user_last_search[user_id]))
        await message.answer(f"⏳ Пожалуйста, подождите {remaining} сек. между поисками.")
        return

    user_last_search[user_id] = now

    # Валидация
    if not validate_fio(message.text):
        await message.answer(
            "❌ Неверный формат ФИО. Используйте кириллицу или латиницу, 2-3 слова (например: Иванов Иван).")
        return

    fio = message.text.strip().title()
    fio_parts = fio.split()

    # Удаление сообщения-запроса (которое просило ввести ФИО)
    data = await state.get_data()
    fio_msg_id = data.get('fio_request_msg_id')
    chat_id = data.get('chat_id')
    if fio_msg_id and chat_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=fio_msg_id)
        except Exception as e:
            logging.error(f"Не удалось удалить сообщение с запросом ФИО: {e}")

    # Удаление самого сообщения пользователя с введённым ФИО
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
    # ПРОВЕРКА КЭША: может, мы это уже искали?
    # ============================================================
    cached_results = check_cache('fio', fio, 'fns')

    if cached_results:
        cache_date = get_cache_date('fio', fio, 'fns')
        days_ago = (datetime.now() - datetime.strptime(cache_date, '%Y-%m-%d')).days

        # Сохраняем данные запроса во временный словарь
        pending_cache_queries[user_id] = {
            "search_type": "fio",
            "search_value": fio,
            "source": "fns"
        }

        # Короткие callback_data с user_id
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Быстрый ответ (из кэша)",
                    callback_data=f"cq_fio_quick_{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Новый поиск (актуальные данные)",
                    callback_data=f"cq_fio_new_{user_id}"
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
            f"✅ *ФИО:* `{fio}` уже найдено в базе данных\n"
            f"📅 Дата последнего обновления: *{cache_date}* ({days_ago} дн. назад)\n"
            f"🔍 Найдено организаций: *{len(cached_results)}*\n\n"
            f"Выберите действие:",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        return  # ВАЖНО: выходим, дальше обработают callbackи в cache_handlers.py

    # ============================================================
    # КЭША НЕТ — запускаем полноценный поиск
    # ============================================================
    if len(fio_parts) == 3:
        search_type_msg = f"🔎 *Полное ФИО:* `{fio}` — будет выполнен *точный поиск*"
    else:
        search_type_msg = f"🔎 *Имя + Фамилия:* `{fio}` — будут найдены *все подходящие записи*"
    await message.answer(f"✅ {search_type_msg}", parse_mode="Markdown")

    await state.set_state(SearchStates.searching)
    cancel_event = asyncio.Event()
    cancel_events[user_id] = cancel_event

    loading_msg = await message.answer(
        "⏳ *Идёт поиск в реестрах ФНС (ЕГРЮЛ/ЕГРИП)...*\n\n"
        "Бот проверяет записи об ИП и организациях. Пожалуйста, подождите. Это может занять несколько минут.\n\n"
        "Вы можете отменить поиск в любой момент.",
        reply_markup=get_cancel_keyboard(), parse_mode="Markdown"
    )

    # Создаем запись в БД и засекаем время
    request_id = create_request(user_db_id, 'fio', fio, 'fns')
    start_time = time.time()

    result = await search_fns(fio, cancel_event)

    # Считаем время выполнения в миллисекундах
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
            f"*По ФИО: {fio}*\n🏛️ ЕГРЮЛ/ЕГРИП: Записей не найдено\n"
            f"🔹 Возможно, человек не является ИП или учредителем компании.",
            reply_markup=get_main_keyboard(), parse_mode="Markdown"
        )
        return

    # Успешный поиск - сохраняем в БД и в КЭШ
    update_request_success(request_id, result['results'], execution_time_ms)
    save_to_cache('fio', fio, 'fns', result['results'])

    # Сохранение результатов для AI-анализа
    ai_analysis_data[user_id] = {
        "search_type": "fio",
        "search_value": fio,
        "results": result['results']
    }

    # ==========================================
    # Формирование и отправка Excel (только для нового поиска)
    # ==========================================
    if result.get("search_type") == "full":
        search_type_text = "точный поиск"
    else:
        search_type_text = "все совпадения"

    await message.answer(
        f"📊 *ЕГРЮЛ/ЕГРИП:* Найдено записей: *{result['count']}* ({search_type_text}). Формирую Excel-файл...",
        parse_mode="Markdown"
    )

    filepath = create_excel_file_fns(fio, result['results'])

    ip_next = result.get('ip_next_url')
    boss_next = result.get('boss_next_url')
    caption_lines = [
        f"📁 *Результаты поиска в ЕГРЮЛ/ЕГРИП по ФИО: {fio}*",
        f"🔹 Найдено записей: *{result['count']}*",
        f"🔹 Источник: ФНС России (list-org.com)"
    ]
    if ip_next or boss_next:
        caption_lines.append("")
        caption_lines.append("⚠️ *В файл вошли не все данные (превышен лимит).*")
        caption_lines.append("Продолжить просмотр на сайте:")
        if ip_next:
            caption_lines.append(f"• [Остальные ИП (стр. {ip_next.split('=')[-1]})]({ip_next})")
        if boss_next:
            caption_lines.append(f"• [Остальные компании (стр. {boss_next.split('=')[-1]})]({boss_next})")

    caption_text = "\n".join(caption_lines)

    await bot.send_chat_action(chat_id=message.chat.id, action="upload_document")
    await message.answer_document(
        document=FSInputFile(filepath),
        caption=caption_text,
        parse_mode="Markdown",
        # Кнопка AI-анализа под Excel-файлом
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 AI-анализ результатов", callback_data="ai_analyze_fio")]
        ])
    )
    await message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())

    try:
        os.remove(filepath)
    except Exception as e:
        logging.error(f"Не удалось удалить файл: {e}")

# ==========================================
# AI-АНАЛИЗ РЕЗУЛЬТАТОВ ПОИСКА
# ==========================================
@router.callback_query(F.data == "ai_analyze_fio")
async def handle_ai_analyze_fio(callback: types.CallbackQuery):
    """Обработчик кнопки AI-анализа для поиска по ФИО."""
    await callback.answer("🤖 Запускаю AI-анализ...")

    user_id = callback.from_user.id
    data = ai_analysis_data.get(user_id)

    if not data:
        await callback.message.answer(
            "⚠️ Нет данных для анализа. Выполните поиск заново.",
            reply_markup=get_main_keyboard()
        )
        return

    loading_msg = await callback.message.answer(
        "⏳ Нейросеть анализирует данные...\nЭто может занять до минуты."
    )

    # Вызываем нейросеть
    analysis = await analyze_search_results(
        data["search_type"],
        data["search_value"],
        data["results"]
    )

    response_text = (
        f"🤖 AI-анализ по запросу: {data['search_value']}\n\n"
        f"{analysis}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Анализ выполнен с помощью DeepSeek AI"
    )

    # Защита от превышения лимита Telegram (4096 символов)
    if len(response_text) > 4096:
        response_text = response_text[:4090] + "…"

    # Отправляем без parse_mode — текст от нейросети может содержать
    # символы *, _, [, которые сломают Markdown-разметку
    await loading_msg.edit_text(response_text)