import asyncio
import os
import time
import logging
import config
from datetime import datetime
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from states import SearchStates
from config import SEARCH_COOLDOWN, MAX_TELEGRAM_MESSAGE_LENGTH
from utils.validators import validate_fio
from utils.keyboards import get_main_keyboard, get_cancel_keyboard
from utils.excel_generator import create_excel_file_fns
from parsers.fns_parser import search_fns
from core import bot, user_last_search, cancel_events, pending_cache_queries

from utils.ai_analyzer import analyze_search_results, ai_answer_query

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

    # Доп. проверка, вызывается ли функция
    print(f"🔍 [DEBUG] process_fns_input вызвана! Текст: '{message.text}'")
    print(f"🔍 [DEBUG] Состояние FSM: {await state.get_state()}")

    user_id = message.from_user.id
    now = asyncio.get_event_loop().time()

    # Проверка на спам (cooldown 60 секунд)
    if user_id in user_last_search and now - user_last_search[user_id] < SEARCH_COOLDOWN:
        remaining = int(SEARCH_COOLDOWN - (now - user_last_search[user_id]))
        await message.answer(f"⏳ Пожалуйста, подождите {remaining} сек. между поисками.")
        return

    # Валидация
    if not validate_fio(message.text):
        await message.answer(
            "❌ Неверный формат ФИО. Используйте кириллицу или латиницу, 2-3 слова (например: Иванов Иван).")
        return

    # Таймер ставим ТОЛЬКО после успешной валидации
    user_last_search[user_id] = now

    fio = message.text.strip().title()
    fio_parts = fio.split()

    # Удаляем сообщение-запрос (которое просило ввести ФИО)
    data = await state.get_data()
    fio_msg_id = data.get('fio_request_msg_id')
    chat_id = data.get('chat_id')
    if fio_msg_id and chat_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=fio_msg_id)
        except Exception as e:
            logging.error(f"Не удалось удалить сообщение с запросом ФИО: {e}")

    # Удаляем само сообщение пользователя с введённым ФИО
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

        # Короткие callback_data с user_id (всё в ASCII, влезает в 64 байта)
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
        return  # ВАЖНО: выходим, дальше обработают callback'и в cache_handlers.py

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

        # Сохраняем пустые результаты для AI-вопроса
        ai_analysis_data[user_id] = {
            "search_type": "fio",
            "search_value": message.text.strip(),
            "results": []
        }

        await message.answer(
            f"*По ФИО: {message.text.strip()}*\n🏛️ ЕГРЮЛ/ЕГРИП: Записей не найдено\n"
            f"🔹 Возможно, человек не является ИП или учредителем компании.\n"
            f"🔹 Иногда при поиске возникают ошибки и результат не показывается. Попробуйте повторить поиск.\n"
            f"🔹 Вы можете задать вопрос нейросети по кнопке ниже.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
            ])
        )
        return

    # Успешный поиск: сохраняем в БД и в КЭШ
    update_request_success(request_id, result['results'], execution_time_ms)
    save_to_cache('fio', fio, 'fns', result['results'])

    # Сохраняем результаты для AI-анализа
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
        # Кнопки AI-анализа и AI-поиска под Excel-файлом
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤖 AI-анализ результатов", callback_data="ai_analyze_fio")],
            [InlineKeyboardButton(text="💬 Задать вопрос нейросети", callback_data="ai_free_search")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]
        ])
    )

    try:
        os.remove(filepath)
    except Exception as e:
        logging.error(f"Не удалось удалить файл: {e}")


# ==========================================
# ИИ-АНАЛИЗ РЕЗУЛЬТАТОВ ПОИСКА
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
        f"💡 Анализ выполнен с помощью нейросети. Рекомендуется проверять важную информацию."
    )

    # Защита от превышения лимита Telegram (4096 символов)
    if len(response_text) > 4096:
        response_text = response_text[:4090] + "…"

    # Отправка без parse_mode, т.к. текст от нейросети может содержать
    # символы *, _, [, которые мешают Markdown-разметке
    await loading_msg.edit_text(response_text)


# ==========================================
# ИИ-ПОИСК: кнопка, чтобы задать вопрос нейросети
# ==========================================
@router.callback_query(F.data == "ai_free_search")
async def handle_ai_free_search(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик кнопки AI-поиска (свободный вопрос нейросети)."""
    await callback.answer()

    user_id = callback.from_user.id
    data = ai_analysis_data.get(user_id)

    if not data:
        await callback.message.answer(
            "⚠️ Нет данных последнего поиска. Сначала выполните поиск.",
            reply_markup=get_main_keyboard()
        )
        return

    # Переводим в состояние ожидания вопроса
    await state.set_state(SearchStates.waiting_for_ai_query)

    # Определяем тип поиска для адаптивной инструкции
    search_type = data.get("search_type", "fio")

    if search_type == "phone":
        # Примеры для поиска по телефону
        examples_text = (
            "💡 *Примеры запросов:*\n"
            "• Расскажи про организации, связанные с этим номером\n"
            "• Есть ли новости или упоминания этих компаний в СМИ?\n"
            "• Какие ещё номера телефонов связаны с этими организациями?\n"
            "• Найди судебные дела или проверки этих компаний\n"
            "• Кто учредители и руководители этих организаций?\n\n"
        )
    else:
        # Примеры для поиска по ФИО (и другим типам)
        examples_text = (
            "💡 *Примеры запросов:*\n"
            "• Расскажи про этого человека всё что найдёшь\n"
            "• Есть ли о нём какие-то новости или упоминания в СМИ?\n"
            "• Какие ещё компании с ним связаны?\n"
            "• Найди судебные дела или исполнительные производства\n"
            "• Проверь, нет ли его в списках дисквалифицированных лиц\n\n"
        )

    await callback.message.answer(
        "🤖 *AI-поиск с использованием интернета*\n\n"
        "📝 *Как формулировать запрос:*\n"
        "Желательно постараться сформулировать вопрос наиболее корректно для получения лучшего и точного результата. "
        "Но, можете написать вопрос так, как вам удобно — своими словами, как будто спрашиваете у человека. "
        "Нейросеть сама поймёт, что нужно искать.\n\n"
        f"{examples_text}"
        "⚠️ _Нейросеть отвечает на основе данных вашего последнего поиска (вывода из истории запросов) и информации из интернета. "
        "Проверяйте важные сведения самостоятельно._\n\n"
        "✏️ Напишите ваш вопрос следующим сообщением.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Отмена (в главное меню)", callback_data="ai_query_cancel")]
        ])
    )

# ==========================================
# Отмена ИИ-поиска
# ==========================================
@router.callback_query(F.data == "ai_query_cancel")
async def handle_ai_query_cancel(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик отмены AI-поиска — возврат в главное меню."""
    await callback.answer()
    await state.clear()

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())


# ==========================================
# Обработчик текста-вопроса для ИИ-поиска (относиться ко всем типам поиска, остальные его импортируют отсюда)
# ==========================================
@router.message(SearchStates.waiting_for_ai_query, lambda message: message.text and not message.text.startswith('/'))
async def process_ai_query(message: types.Message, state: FSMContext):
    """Принимает вопрос пользователя и передаёт его нейросети с веб-поиском."""
    import asyncio

    user_id = message.from_user.id
    data = ai_analysis_data.get(user_id)

    # Выходим из состояния ожидания в любом случае
    await state.clear()

    if not data:
        await message.answer(
            "⚠️ Нет данных последнего поиска. Сначала выполните поиск.",
            reply_markup=get_main_keyboard()
        )
        return

    # Показываем индикатор "печатает..."
    await bot.send_chat_action(chat_id=message.chat.id, action="typing")

    loading_msg = await message.answer(
        "⏳ *Запрос принят, идет обработка...*\n\n"
        "🔍 Модель анализирует ваш запрос и скоро предоставит "
        "готовый результат.\n\n"
        "Это может занять несколько минут.\n\n"
        "_Пожалуйста, подождите..._",
        parse_mode="Markdown"
    )

    # Фоновая задача: обновлять сообщение каждые 20 секунд
    stop_progress = asyncio.Event()

    async def progress_updater():
        elapsed = 0
        try:
            while not stop_progress.is_set():
                await asyncio.sleep(20)
                elapsed += 20
                try:
                    await bot.send_chat_action(chat_id=message.chat.id, action="typing")
                    await loading_msg.edit_text(
                        f"⏳ *Идет обработка...*\n\n"
                        f"🔍 Прошло {elapsed} секунд\n"
                        f"Модель скоро сформирует готовый ответ.\n\n"
                        "_Пожалуйста, подождите..._",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    progress_task = asyncio.create_task(progress_updater())

    try:
        # Вызываем нейросеть с веб-поиском
        answer = await ai_answer_query(
            message.text,
            data["search_type"],
            data["search_value"],
            data["results"]
        )

        # Останавливаем прогресс-апдейтер
        stop_progress.set()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        # ВАЖНО: для длинных ответов — разбиваем на части
        # Источники обычно в конце, поэтому их важно сохранить
        response_header = (
            f"🤖 *Ответ на вопрос:* {message.text}\n\n"
        )
        response_footer = (
            f"\n\n━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 Ответ подготовлен с помощью нейросети. Рекомендуется проверять важную информацию."
        )

        # Полная длина с шапкой и подвалом
        full_response = response_header + answer + response_footer

        if len(full_response) <= config.MAX_TELEGRAM_MESSAGE_LENGTH:
            # Ответ помещается — отправляем одним сообщением
            try:
                await loading_msg.edit_text(full_response)
            except Exception as e:
                logging.warning(f"Не удалось обновить сообщение: {e}")
                await message.answer(full_response)
        else:
            # Ответ слишком длинный — удаляем loading и отправляем частями
            try:
                await loading_msg.delete()
            except Exception:
                pass

            # Отправляем шапку + начало ответа
            await message.answer(response_header)

            # Разбиваем основной ответ на части по ~3800 символов
            # (с запасом, чтобы не было обрезки)
            chunk_size = 3800
            chunks = []
            for i in range(0, len(answer), chunk_size):
                chunks.append(answer[i:i + chunk_size])

            # Отправляем все части, кроме последней
            for chunk in chunks[:-1]:
                await message.answer(chunk)
                await asyncio.sleep(0.3)  # небольшая пауза между сообщениями

            # Последняя часть — с подвалом
            await message.answer(chunks[-1] + response_footer)

    except Exception as e:
        # Останавливаем прогресс-апдейтер при ошибке
        stop_progress.set()
        progress_task.cancel()
        try:
            await progress_task
        except asyncio.CancelledError:
            pass

        # Проверка на пустой ответ от нейросети
        if not answer or not answer.strip():
            try:
                await loading_msg.edit_text(
                    "⚠️ Не удалось получить ответ от нейросети.\n"
                    "Попробуйте задать вопрос ещё раз."
                )
            except Exception:
                await message.answer(
                    "⚠️ Не удалось получить ответ от нейросети.\n"
                    "Попробуйте задать вопрос ещё раз."
                )
            # Показываем меню и выходим
            await message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())
            return

        logging.error(f"Ошибка в process_ai_query: {e}", exc_info=True)
        try:
            await loading_msg.edit_text(
                f"⚠️ Произошла ошибка при поиске:\n`{str(e)[:200]}`\n\n"
                f"Попробуй задать вопрос ещё раз.",
                parse_mode="Markdown"
            )
        except Exception:
            await message.answer(f"⚠️ Ошибка: {str(e)[:200]}")

    # После ответа — в главное меню
    await message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())