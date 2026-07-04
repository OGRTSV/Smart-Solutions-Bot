"""
Обработчики для GitHub-поиска: поиск по нику, просмотр репозиториев/активности,
сравнение двух разработчиков. Интеграция с БД для сохранения в историю.
"""

import json
import logging
import asyncio
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from states import SearchStates
from parsers.github_parser import (
    search_github,
    get_repos,
    get_user_events,
    analyze_repos,
    analyze_activity
)
from utils.formatters import (
    format_github_profile,
    format_github_repos,
    format_github_activity,
    format_github_compare
)
from utils.keyboards import (
    get_github_menu_keyboard,
    get_github_profile_actions,
    get_github_back_to_profile,
    get_main_keyboard,
    get_cancel_keyboard_github,
    get_github_compare_actions
)
from utils.validators import validate_github_username
from utils.database import (
    get_or_create_user,
    create_request,
    update_request_success,
    update_request_error
)

logger = logging.getLogger(__name__)
router = Router()


# ============================================================
# 🐙 ОТКРЫТИЕ МЕНЮ GITHUB
# ============================================================
@router.callback_query(F.data == "open_github_menu")
async def open_github_menu(callback: types.CallbackQuery, state: FSMContext):
    """Открывает подменю GitHub из главного меню."""
    await callback.answer()
    await state.clear()

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "🐙 *Поиск по GitHub*\n\n"
        "Выберите действие:",
        reply_markup=get_github_menu_keyboard(),
        parse_mode="Markdown"
    )


# ============================================================
# 🔍 ПОИСК ПО НИКУ GITHUB
# ============================================================
@router.callback_query(F.data == "github_search_username")
async def start_github_search(callback: types.CallbackQuery, state: FSMContext):
    """Запрашивает у пользователя никнейм GitHub."""
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        pass

    await state.set_state(SearchStates.waiting_github_username)
    await callback.message.answer(
        "🔍 *Поиск по нику GitHub*\n\n"
        "Введите никнейм пользователя на GitHub:\n"
        "_Например: `torvalds` или `@torvalds`_\n\n"
        "💡 Для отмены введите /start",
        parse_mode="Markdown",
        reply_markup = get_cancel_keyboard_github()
    )


@router.message(SearchStates.waiting_github_username, lambda message: message.text and not message.text.startswith('/'))
async def process_github_username(message: types.Message, state: FSMContext):
    """Обрабатывает введённый никнейм, делает запрос к API и выводит результат."""

    username = message.text.strip()

    # Валидация никнейма
    valid_username = validate_github_username(username)
    if not valid_username:
        await message.answer(
            "❌ Неверный формат никнейма.\n\n"
            "Никнейм GitHub должен:\n"
            "• Содержать только латинские буквы, цифры и дефисы\n"
            "• Быть длиной от 1 до 39 символов\n"
            "• Не начинаться и не заканчиваться дефисом\n"
            "• Не содержать два дефиса подряд",
        )
        return

    # Сбрасываем состояние ДО запроса, чтобы не было зависаний
    await state.clear()

    # Показываем индикатор загрузки
    loading_msg = await message.answer("⏳ Загружаю данные с GitHub...")

    # Получаем ID пользователя из БД
    user_db_id = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    # Создаём запись в БД
    request_id = create_request(user_db_id, 'github', valid_username, 'github_api')

    try:
        # Делаем запрос к GitHub API
        result = await search_github(valid_username)

        # Удаляем сообщение загрузки
        try:
            await loading_msg.delete()
        except Exception:
            pass

        if not result["found"]:
            # Пользователь не найден
            update_request_error(request_id, 'not_found', result['error'])
            await message.answer(
                f"❌ {result['error']}",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return

        # Пользователь найден — сохраняем в БД
        # Сохраняем user + repos_stats в results_json
        combined_results = {
            "user": result["user"],
            "repos_stats": result["repos_stats"]
        }
        update_request_success(request_id, [combined_results], 0)

        # Форматируем и отправляем профиль
        profile_text = format_github_profile(result["user"], result["repos_stats"])

        await message.answer(
            profile_text,
            parse_mode="Markdown",
            reply_markup=get_github_profile_actions(valid_username),
            disable_web_page_preview=True
        )

    except Exception as e:
        logger.error(f"Ошибка при поиске GitHub {valid_username}: {e}")
        update_request_error(request_id, 'api_error', str(e))
        try:
            await loading_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ Произошла ошибка при обращении к GitHub API: {str(e)}",
            reply_markup=get_main_keyboard()
        )


# ============================================================
# 📁 ПОКАЗ РЕПОЗИТОРИЕВ (inline-кнопка)
# ============================================================
@router.callback_query(F.data.startswith("github_repos:"))
async def show_github_repos(callback: types.CallbackQuery):
    """Показывает топ-репозитории пользователя."""
    await callback.answer("⏳ Загружаю репозитории...")

    username = callback.data.split(":", 1)[1]

    try:
        await callback.message.edit_text("⏳ Загружаю репозитории...")
    except Exception:
        pass

    # Получаем репозитории из API (не из БД!)
    repos = await get_repos(username)
    repos_stats = analyze_repos(repos)

    if not repos_stats or not repos_stats.get("top_repos"):
        text = f"📭 У пользователя `{username}` нет публичных репозиториев."
    else:
        text = format_github_repos(repos_stats, username)

    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_github_back_to_profile(username),
            disable_web_page_preview=False
        )
    except Exception as e:
        logger.error(f"Ошибка при показе репозиториев: {e}")
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_github_back_to_profile(username),
            disable_web_page_preview=False
        )


# ============================================================
# 📈 ПОКАЗ АКТИВНОСТИ (inline-кнопка)
# ============================================================
@router.callback_query(F.data.startswith("github_activity:"))
async def show_github_activity(callback: types.CallbackQuery):
    """Показывает последнюю активность пользователя."""
    await callback.answer("⏳ Загружаю активность...")

    username = callback.data.split(":", 1)[1]

    try:
        await callback.message.edit_text("⏳ Загружаю активность...")
    except Exception:
        pass

    # Получаем события из API
    events = await get_user_events(username)
    activity = analyze_activity(events)

    text = format_github_activity(activity, username)

    try:
        await callback.message.edit_text(
            text,
            parse_mode="Markdown",
            reply_markup=get_github_back_to_profile(username)
        )
    except Exception as e:
        logger.error(f"Ошибка при показе активности: {e}")
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=get_github_back_to_profile(username)
        )


# ============================================================
# ◀️ ВОЗВРАТ К ПРОФИЛЮ
# ============================================================
@router.callback_query(F.data.startswith("github_back_profile:"))
async def back_to_github_profile(callback: types.CallbackQuery):
    """Возвращает к основному профилю из репозиториев/активности."""
    await callback.answer("⏳ Загружаю профиль...")

    username = callback.data.split(":", 1)[1]

    # Делаем новый запрос к API для получения актуальных данных
    result = await search_github(username)

    if not result["found"]:
        await callback.message.answer(
            f"❌ {result['error']}",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )
        return

    profile_text = format_github_profile(result["user"], result["repos_stats"])

    try:
        await callback.message.edit_text(
            profile_text,
            parse_mode="Markdown",
            reply_markup=get_github_profile_actions(username),
            disable_web_page_preview=True
        )
    except Exception as e:
        logger.error(f"Ошибка при возврате к профилю: {e}")
        await callback.message.answer(
            profile_text,
            parse_mode="Markdown",
            reply_markup=get_github_profile_actions(username),
            disable_web_page_preview=True
        )


# ============================================================
# ⚔️ СРАВНЕНИЕ ДВУХ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================
@router.callback_query(F.data == "github_compare_start")
async def start_github_compare(callback: types.CallbackQuery, state: FSMContext):
    """Запускает пошаговый ввод двух никнеймов для сравнения."""
    await callback.answer()

    try:
        await callback.message.delete()
    except Exception:
        pass

    await state.set_state(SearchStates.waiting_github_compare_1)
    await callback.message.answer(
        "⚔️ *Сравнение двух разработчиков*\n\n"
        "Введите никнейм *первого* пользователя на GitHub:\n\n"
        "💡 Для отмены введите /start",
        parse_mode="Markdown",
        reply_markup = get_cancel_keyboard_github()
    )


@router.message(SearchStates.waiting_github_compare_1, lambda message: message.text and not message.text.startswith('/'))
async def process_github_compare_1(message: types.Message, state: FSMContext):
    """Обрабатывает первый никнейм и запрашивает второй."""

    username = message.text.strip()

    valid_username = validate_github_username(username)

    if not valid_username:
        await message.answer(
            "❌ Неверный формат никнейма. Попробуйте ещё раз:\n"
            "_Например: `torvalds`_\n\n"
            "💡 Для отмены введите /start",
            parse_mode="Markdown"
        )
        return

    # Сохраняем первый никнейм в состоянии
    await state.update_data(user1=valid_username)
    await state.set_state(SearchStates.waiting_github_compare_2)

    await message.answer(
        f"✅ Первый: `{valid_username}`\n\n"
        f"Теперь введите никнейм *второго* пользователя:",
        parse_mode="Markdown"
    )


@router.message(SearchStates.waiting_github_compare_2, lambda message: message.text and not message.text.startswith('/'))
async def process_github_compare_2(message: types.Message, state: FSMContext):
    """Обрабатывает второй никнейм, делает сравнение и выводит результат."""

    username2 = message.text.strip()

    valid_username2 = validate_github_username(username2)

    if not valid_username2:
        await message.answer(
            "❌ Неверный формат никнейма. Попробуйте ещё раз:\n"
            "_Например: `gvanrossum`_\n\n"
            "💡 Для отмены введите /start",
            parse_mode="Markdown"
        )
        return

    # Получаем первый никнейм из состояния
    data = await state.get_data()
    valid_username1 = data.get("user1")

    # Сбрасываем состояние
    await state.clear()

    # Показываем индикатор загрузки
    loading_msg = await message.answer(
        f"⏳ Загружаю данные обоих пользователей...\n\n"
        f"• `{valid_username1}`\n"
        f"• `{valid_username2}`",
        parse_mode="Markdown"
    )

    # Получаем ID пользователя из БД
    user_db_id = get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    # Создаём запись в БД (сохраняем оба никнейма через запятую)
    compare_value = f"{valid_username1} vs {valid_username2}"
    request_id = create_request(user_db_id, 'github_compare', compare_value, 'github_api')

    try:
        # Делаем запросы к API для обоих пользователей
        user1_data = await search_github(valid_username1)
        user2_data = await search_github(valid_username2)

        # Удаляем сообщение загрузки
        try:
            await loading_msg.delete()
        except Exception:
            pass

        # Проверяем, найдены ли оба пользователя
        if not user1_data["found"]:
            update_request_error(request_id, 'not_found', f"Пользователь {valid_username1} не найден")
            await message.answer(
                f"❌ Пользователь `{valid_username1}` не найден на GitHub.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return

        if not user2_data["found"]:
            update_request_error(request_id, 'not_found', f"Пользователь {valid_username2} не найден")
            await message.answer(
                f"❌ Пользователь `{valid_username2}` не найден на GitHub.",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
            return

        # Сохраняем успешное сравнение в БД
        combined_results = {
            "user1": user1_data["user"],
            "stats1": user1_data["repos_stats"],
            "user2": user2_data["user"],
            "stats2": user2_data["repos_stats"]
        }
        update_request_success(request_id, [combined_results], 0)

        # Форматируем и отправляем сравнение
        compare_text = format_github_compare(
            user1_data["user"],
            user1_data["repos_stats"],
            user2_data["user"],
            user2_data["repos_stats"]
        )

        await message.answer(
            compare_text,
            parse_mode="Markdown",
            reply_markup=get_github_compare_actions(valid_username1, valid_username2)
        )

    except Exception as e:
        logger.error(f"Ошибка при сравнении {valid_username1} vs {valid_username2}: {e}")
        update_request_error(request_id, 'api_error', str(e))
        try:
            await loading_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ Произошла ошибка при обращении к GitHub API: {str(e)}",
            reply_markup=get_main_keyboard()
        )