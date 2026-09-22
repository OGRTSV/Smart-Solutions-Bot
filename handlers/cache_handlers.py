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
from utils.excel_generator import create_excel_file_fns, create_excel_file_phone, create_excel_file_username
from parsers.fns_parser import search_fns
from parsers.phone_parser import search_phone_org
from parsers.username_parser import search_username
from core import bot, cancel_events, pending_cache_queries
from utils.database import (
    get_or_create_user,
    create_request,
    update_request_success,
    update_request_error,
    check_cache,
    save_to_cache,
    get_cache_date,
    get_cache_phone_info
)

# Отдельные импорты для ИИ-анализа
from handlers.fio_search import ai_analysis_data
from utils.ai_analyzer import analyze_search_results

router = Router()


@router.callback_query(F.data.startswith("cq_fio_") | F.data.startswith("cq_phone_") | F.data.startswith("cq_username_"))
async def handle_cache_choice(callback: types.CallbackQuery, state: FSMContext):
    """
    Единый обработчик для всех кнопок кэша.
    Берёт данные из временного словаря pending_cache_queries.
    """
    await callback.answer()

    user_id = callback.from_user.id

    # Получение данных из временного словаря
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

    # Удаление данные из словаря (они больше не нужны)
    pending_cache_queries.pop(user_id, None)

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

        # Сохранение в истории
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
                f"📊 *ЕГРЮЛ/ЕГРИП:* Найдено записей: *{len(cached_results)}* (из кэша). Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_fns(search_value, cached_results)

            caption_text = (
                f"📁 *Результаты поиска в ЕГРЮЛ/ЕГРИП по ФИО: {search_value}*\n"
                f"🔹 Найдено записей: *{len(cached_results)}*\n"
                f"🔹 Источник: ФНС России (list-org.com)\n"
                f"🔹 Данные из кэша (обновлено {cache_date})"
            )

            # Сохранение данных для ИИ-анализа
            ai_analysis_data[user_id] = {
                "search_type": "fio",
                "search_value": search_value,
                "results": cached_results
            }

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 AI-анализ результатов", callback_data="ai_analyze_fio")],
                    [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                    [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                ])
            )

        elif search_type == 'phone':
            # Получаем phone_info из кэша
            phone_info = get_cache_phone_info('phone', search_value, 'listorg')

            # Данные о номере (регион и оператор)
            info_line = f"📡 {phone_info} _(первый оператор, текущий может отличаться)_\n" if phone_info else ""

            await callback.message.answer(
                f"✅ *Номер:* `{search_value}`\n"
                f"{info_line}"
                f"📅 _Данные из кэша (обновлено {cache_date})_",
                parse_mode="Markdown"
            )

            await callback.message.answer(
                f"📊 *Найдено организаций: {len(cached_results)}* (из кэша). Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_phone(search_value, cached_results)

            caption_text = (
                f"📁 *Результаты поиска по телефону: {search_value}*\n"
                f"🔹 Найдено организаций: *{len(cached_results)}*\n"
                f"🔹 Источник: list-org.com\n"
                f"🔹 Данные из кэша (обновлено {cache_date})"
            )

            # Добавляем phone_info в caption
            if phone_info:
                caption_text += f"\n📡 {phone_info} _(первый оператор, текущий может отличаться)_"

            # Сохранение данных для ИИ-анализа
            ai_analysis_data[user_id] = {
                "search_type": "phone",
                "search_value": search_value,
                "results": cached_results
            }

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 AI-анализ результатов", callback_data="ai_analyze_phone")],
                    [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                    [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                ])
            )

        elif search_type == 'username':
            # 👤 НОВАЯ ВЕТКА для username
            await callback.message.answer(
                f"✅ *Username:* `{search_value}`\n"
                f"📅 _Данные из кэша (обновлено {cache_date})_",
                parse_mode="Markdown"
            )

            await callback.message.answer(
                f"🌐 *Найдено профилей: {len(cached_results)}* (из кэша). Формирую Excel-файл...",
                parse_mode="Markdown"
            )

            filepath = create_excel_file_username(search_value, cached_results)

            caption_text = (
                f"📁 *Результаты поиска по username: {search_value}*\n"
                f"🔹 Найдено профилей: *{len(cached_results)}*\n"
                f"🔹 Источник: мультиплатформенная база\n"
                f"🔹 Данные из кэша (обновлено {cache_date})"
                f"\n⚠️ _Внимание: некоторые ссылки могут быть неточными (ложные срабатывания). Рекомендуем проверять ключевые профили вручную._"
            )

            # Сохранение данных для ИИ-анализа
            ai_analysis_data[user_id] = {
                "search_type": "username",
                "search_value": search_value,
                "results": cached_results
            }

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 AI-анализ профилей", callback_data="ai_analyze_username")],
                    [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                    [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                ])
            )

        # Удаление временного файа
        try:
            os.remove(filepath)
        except Exception as e:
            logging.error(f"Не удалось удалить файл: {e}")

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

                # Сохраняем пустые результаты для AI-вопроса
                ai_analysis_data[user_id] = {
                    "search_type": "fio",
                    "search_value": search_value,
                    "results": []
                }

                await callback.message.answer(
                    f"✅ *По ФИО: {search_value}*\n🏛️ ЕГРЮЛ/ЕГРИП: Записей не найдено\n"
                    f"🔹 Возможно, человек не является ИП или учредителем компании.\n"
                    f"🔹 Попробуйте задать вопрос нейросети по кнопке ниже.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                    ])
                )
                return

            # Обновление кэша
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

            # Сохранение данных для ИИ-анализа
            ai_analysis_data[user_id] = {
                "search_type": "fio",
                "search_value": search_value,
                "results": result['results']
            }

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 AI-анализ результатов", callback_data="ai_analyze_fio")],
                    [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                    [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                ])
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
            # Извлекаем данные о номере только один раз, в самом начале
            phone_info = result.get("phone_info")

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
                update_request_success(request_id, [], execution_time_ms, phone_info=result.get("phone_info"))

                # Сохраняем пустые результаты для AI-вопроса
                ai_analysis_data[user_id] = {
                    "search_type": "phone",
                    "search_value": search_value,
                    "results": []
                }

                # Данные о номере (регион и оператор)
                info_line = f"📡 {phone_info} _(первый зарегестрированный оператор, текущий может отличаться)_\n" if phone_info else ""
                await callback.message.answer(
                    f"✅ *По номеру: {search_value}*\n"
                    f"{info_line}"
                    f"🔹 Организаций не найдено\n"
                    f"🔹 Возможно, номер не зарегистрирован на юридическое лицо.\n"
                    f"🔹 Попробуйте задать вопрос нейросети по кнопке ниже.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                    ])
                )
                return

            # Обновление кэша
            update_request_success(request_id, result['results'], execution_time_ms, phone_info=result.get("phone_info"))
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
            # Данные о номере в caption
            if phone_info:
                caption_text += f"\n📡 {phone_info} _(первый зарестрированный оператор, текущий может отличаться)_"

            # Сохранение данных для ИИ-анализа
            ai_analysis_data[user_id] = {
                "search_type": "phone",
                "search_value": search_value,
                "results": result['results']
            }

            await bot.send_chat_action(chat_id=callback.message.chat.id, action="upload_document")
            await callback.message.answer_document(
                document=FSInputFile(filepath),
                caption=caption_text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🤖 AI-анализ результатов", callback_data="ai_analyze_phone")],
                    [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                    [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                ])
            )

        elif search_type == 'username':
            # 👤 НОВАЯ ВЕТКА для username (новый поиск)
            loading_msg = await callback.message.answer(
                "⏳ *Идёт поиск username по платформам...*\n\n"
                "Бот проверяет наличие этого ника на множестве сайтов (GitHub, VK, Telegram и др.).\n\n"
                "Пожалуйста, подождите. Это может занять 1-2 минуты.\n\n"
                "Вы можете отменить поиск в любой момент.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )

            request_id = create_request(user_db_id, 'username', search_value, 'multiplatform')
            start_time = time.time()

            result = await search_username(search_value, cancel_event)
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

                # Сохраняем пустые результаты для AI-вопроса
                ai_analysis_data[user_id] = {
                    "search_type": "username",
                    "search_value": search_value,
                    "results": []
                }

                await callback.message.answer(
                    f"*По username: {search_value}*\n\n"
                    f"🌐 Профилей не найдено\n"
                    f"🔹 Проверено сайтов: *{result['checked']}*\n"
                    f"🔹 Возможно, этот ник не используется или используется редко.\n"
                    f"🔹 Попробуйте задать вопрос нейросети по кнопке ниже.",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
                    ])
                )
                return

            # Обновление кэша
            update_request_success(request_id, result['results'], execution_time_ms)
            save_to_cache('username', search_value, 'multiplatform', result['results'])

            today = datetime.now().strftime('%d.%m.%Y')

            # Сохранение данных для ИИ-анализа
            ai_analysis_data[user_id] = {
                "search_type": "username",
                "search_value": search_value,
                "results": result['results']
            }

            await _show_username_results_from_cache(callback.message, search_value, result)

        # Удаление временного файла
        try:
            os.remove(filepath)
        except Exception as e:
            logging.error(f"Не удалось удалить файл: {e}")


async def _show_username_results_from_cache(message: types.Message, username: str, result: dict):
    """Вспомогательная функция для показа результатов username-поиска из кэша."""
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