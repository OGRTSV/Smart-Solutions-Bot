# handlers/cache_handlers.py
import asyncio
import os
import time
import logging
from datetime import datetime
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from states import SearchStates
from utils.keyboards import get_main_keyboard, get_cancel_keyboard
from utils.excel_generator import create_excel_file_fns, create_excel_file_phone
from parsers.fns_parser import search_fns
from parsers.phone_parser import search_phone_org
from core import bot, cancel_events, pending_cache_queries
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


@router.callback_query(F.data.startswith("cq_fio_") | F.data.startswith("cq_phone_"))
async def handle_cache_choice(callback: types.CallbackQuery, state: FSMContext):
    """
    Единый обработчик для всех кнопок кэша.
    Берёт данные из временного словаря pending_cache_queries.
    """
    await callback.answer()

    user_id = callback.from_user.id

    # 🆕 Получаем данные из временного словаря
    query_data = pending_cache_queries.get(user_id)

    if not query_data:
        await callback.message.answer(
            "❌ Данные запроса не найдены. Пожалуйста, начните поиск заново."
        )
        return

    search_type = query_data["search_type"]
    search_value = query_data["search_value"]
    source = query_data["source"]
    action = "quick" if "quick" in callback.data else "new"

    # Удаляем данные из словаря (они больше не нужны)
    pending_cache_queries.pop(user_id, None)

    # Удаляем сообщение с кнопками
    try:
        await callback.message.delete()
    except:
        pass

    # ============================================
    # БЫСТРЫЙ ОТВЕТ ИЗ КЭША
    # ============================================
    if action == "quick":
        cached_results = check_cache(search_type, search_value, source)

        if not cached_results:
            await callback.message.answer("❌ Данные в кэше не найдены (возможно, устарели)")
            return

        cache_date = get_cache_date(search_type, search_value, source)

        # Сохраняем в историю
        user_db_id = get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name
        )
        request_id = create_request(user_db_id, search_type, search_value, source)
        update_request_success(request_id, cached_results, 0)

        if search_type == 'fio':
            await callback.message.answer(
                f"✅ *ФИО:* `{search_value}`\n"
                f"📅 _Данные из кэша (обновлено {cache_date})_",
                parse_mode="Markdown"
            )

            await callback.message.answer(
                f"📊 *ЕГРЮЛ/ЕГРИП:* Найдено записей: *{len(cached_results)}* (⚡ из кэша). Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_fns(search_value, cached_results)

            caption_text = (
                f"📁 *Результаты поиска в ЕГРЮЛ/ЕГРИП по ФИО: {search_value}*\n"
                f"🔹 Найдено записей: *{len(cached_results)}*\n"
                f"🔹 Источник: ФНС России (list-org.com)\n"
                f"🔹 Данные из кэша (обновлено {cache_date})"
            )

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown"
            )

        elif search_type == 'phone':
            await callback.message.answer(
                f"✅ *Номер:* `{search_value}`\n"
                f"📅 _Данные из кэша (обновлено {cache_date})_",
                parse_mode="Markdown"
            )

            await callback.message.answer(
                f"📊 *Найдено организаций: {len(cached_results)}* (⚡ из кэша). Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_phone(search_value, cached_results)

            caption_text = (
                f"📁 *Результаты поиска по телефону: {search_value}*\n"
                f"🔹 Найдено организаций: *{len(cached_results)}*\n"
                f"🔹 Источник: list-org.com\n"
                f"🔹 Данные из кэша (обновлено {cache_date})"
            )

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown"
            )

        # Удаляем временный файл
        try:
            os.remove(filepath)
        except Exception as e:
            logging.error(f"Не удалось удалить файл: {e}")

        await callback.message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())

    # ============================================
    # НОВЫЙ ПОИСК (АКТУАЛЬНЫЕ ДАННЫЕ)
    # ============================================
    elif action == "new":
        user_db_id = get_or_create_user(
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name
        )

        await state.set_state(SearchStates.searching)
        cancel_event = asyncio.Event()
        cancel_events[user_id] = cancel_event

        if search_type == 'fio':
            loading_msg = await callback.message.answer(
                "⏳ *Идёт поиск в реестрах ФНС (ЕГРЮЛ/ЕГРИП)...*\n\n"
                "Бот проверяет записи об ИП и организациях. Пожалуйста, подождите. Это может занять несколько минут.\n\n"
                "Вы можете отменить поиск в любой момент.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )

            request_id = create_request(user_db_id, 'fio', search_value, 'fns')
            start_time = time.time()

            result = await search_fns(search_value, cancel_event)
            execution_time_ms = int((time.time() - start_time) * 1000)

            if result.get("cancelled"):
                update_request_error(request_id, 'cancelled', 'Отменено пользователем')
                cancel_events.pop(user_id, None)
                await state.clear()
                return

            try:
                await loading_msg.delete()
            except:
                pass

            cancel_events.pop(user_id, None)
            await state.clear()

            if "error" in result:
                update_request_error(request_id, 'parser_error', result['error'])
                await callback.message.answer(f"❌ Ошибка: {result['error']}")
                return

            if not result.get("found"):
                update_request_success(request_id, [], execution_time_ms)
                await callback.message.answer(
                    f"✅ *По ФИО: {search_value}*\n🏛️ ЕГРЮЛ/ЕГРИП: Записей не найдено\n"
                    f"🔹 Возможно, человек не является ИП или учредителем компании.",
                    parse_mode="Markdown"
                )
                return

            # Обновляем кэш
            update_request_success(request_id, result['results'], execution_time_ms)
            save_to_cache('fio', search_value, 'fns', result['results'])

            today = datetime.now().strftime('%d.%m.%Y')

            await callback.message.answer(
                f"✅ *Актуальные данные на {today}*\n"
                f"📊 *ЕГРЮЛ/ЕГРИП:* Найдено записей: *{result['count']}*. Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_fns(search_value, result['results'])

            ip_next = result.get('ip_next_url')
            boss_next = result.get('boss_next_url')
            caption_lines = [
                f"📁 *Результаты поиска в ЕГРЮЛ/ЕГРИП по ФИО: {search_value}*",
                f"🔹 Найдено записей: *{result['count']}*",
                f"🔹 Источник: ФНС России (list-org.com)",
                f"🔹 Актуальные данные на {today}"
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

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown"
            )

        elif search_type == 'phone':
            loading_msg = await callback.message.answer(
                "⏳ *Идёт поиск организаций по номеру телефона...*\n\n"
                "Проверяем базы данных. Пожалуйста, подождите. Это может занять несколько минут.\n\n"
                "Вы можете отменить поиск в любой момент.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )

            request_id = create_request(user_db_id, 'phone', search_value, 'listorg')
            start_time = time.time()

            result = await search_phone_org(search_value, cancel_event)
            execution_time_ms = int((time.time() - start_time) * 1000)

            if result.get("cancelled"):
                update_request_error(request_id, 'cancelled', 'Отменено пользователем')
                cancel_events.pop(user_id, None)
                await state.clear()
                return

            try:
                await loading_msg.delete()
            except:
                pass

            cancel_events.pop(user_id, None)
            await state.clear()

            if "error" in result:
                update_request_error(request_id, 'parser_error', result['error'])
                await callback.message.answer(f"❌ Ошибка: {result['error']}")
                return

            if not result.get("found"):
                update_request_success(request_id, [], execution_time_ms)
                await callback.message.answer(
                    f"✅ *По номеру: {search_value}*\n"
                    f"🔹 Организаций не найдено\n"
                    f"🔹 Возможно, номер не зарегистрирован на юридическое лицо.",
                    parse_mode="Markdown"
                )
                return

            # Обновляем кэш
            update_request_success(request_id, result['results'], execution_time_ms)
            save_to_cache('phone', search_value, 'listorg', result['results'])

            today = datetime.now().strftime('%d.%m.%Y')

            await callback.message.answer(
                f"✅ *Актуальные данные на {today}*\n"
                f"📊 *Найдено организаций: {result['count']}*. Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_phone(search_value, result['results'])

            caption_text = (
                f"📁 *Результаты поиска по телефону: {search_value}*\n"
                f"🔹 Найдено организаций: *{result['count']}*\n"
                f"🔹 Источник: list-org.com\n"
                f"🔹 Актуальные данные на {today}"
            )

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown"
            )

        # Удаляем временный файл
        try:
            os.remove(filepath)
        except Exception as e:
            logging.error(f"Не удалось удалить файл: {e}")

        await callback.message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())