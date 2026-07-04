import logging
from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext

from states import SearchStates
from utils.keyboards import get_main_keyboard, get_source_keyboard, get_phone_source_keyboard, \
    get_fio_navigation_keyboard, get_phone_navigation_keyboard
from core import cancel_events

router = Router()


@router.callback_query(F.data.in_(["search_phone", "search_fio", "search_plate"]))
async def process_search_choice(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    if callback.data == "search_phone":
        await state.set_state(SearchStates.waiting_for_phone_source)
        await callback.message.answer(
            "📱 *Выбран поиск по телефону.*\n\n"
            "Выберите источник для поиска:",
            reply_markup=get_phone_source_keyboard(),
            parse_mode="Markdown"
        )

    elif callback.data == "search_fio":
        await state.set_state(SearchStates.waiting_for_source)
        await callback.message.answer(
            "👤 *Выбран поиск по ФИО*\n\nВыберите источник для поиска:",
            reply_markup=get_source_keyboard(),
            parse_mode="Markdown"
        )

    elif callback.data == "search_plate":
        await state.set_state(SearchStates.waiting_for_plate)
        await callback.message.answer("🚗 Введите госномер автомобиля (например: А123ВС77 или А123ВС777):")


@router.callback_query(F.data == "back_to_phone_source")
async def back_to_phone_source(callback: types.CallbackQuery, state: FSMContext):
    """Возврат к выбору источника для телефона."""
    await state.set_state(SearchStates.waiting_for_phone_source)
    await callback.answer()

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "📱 *Выбран поиск по телефону*\n\n"
        "Выберите источник для поиска:",
        reply_markup=get_phone_source_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "phone_source_listorg", SearchStates.waiting_for_phone_source)
async def process_phone_source_listorg(callback: types.CallbackQuery, state: FSMContext):
    """Обработчик выбора list-org.com для поиска по телефону."""
    await callback.answer()
    await state.set_state(SearchStates.waiting_for_phone)

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    msg = await callback.message.answer(
        "🏢 *Выбран поиск по организациям.*\n\n"
        "📞 Введите номер телефона для поиска организаций:\n"
        "_Формат: 89991234567 или +79991234567_",
        reply_markup=get_phone_navigation_keyboard(),
        parse_mode="Markdown"
    )

    await state.update_data(phone_request_msg_id=msg.message_id, chat_id=msg.chat.id)


@router.callback_query(F.data == "source_fns", SearchStates.waiting_for_source)
async def process_source_choice_fns(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(SearchStates.waiting_for_fns)

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    msg = await callback.message.answer(
        "🏛️ *Выбран источник: ЕГРЮЛ/ЕГРИП (ФНС)*\n\n"
        "👤 Введите ФИО (например: Иванов Иван Иванович)\n"
        "_Пожалуйста, вводите четко без ошибок. Так результат будет наиболее точным._\n\n"
        "💡 *Подсказка:*\n"
        "• Если ввести *Имя + Фамилия* — бот найдёт всех людей с таким именем\n"
        "• Если ввести *полное ФИО* — бот найдёт точное совпадение",
        reply_markup=get_fio_navigation_keyboard(),
        parse_mode="Markdown"
    )

    await state.update_data(fio_request_msg_id=msg.message_id, chat_id=msg.chat.id)


@router.callback_query(F.data == "back_to_search")
async def back_to_search(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "🔍 Выберите тип поиска из меню ниже:",
        reply_markup=get_main_keyboard()
    )


@router.callback_query(F.data == "back_to_source")
async def back_to_source(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_source)
    await callback.answer()

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "👤 *Выбран поиск по ФИО*\n\nВыберите источник для поиска:",
        reply_markup=get_source_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.answer()

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "🔍 Выберите тип поиска из меню ниже:",
        reply_markup=get_main_keyboard()
    )


@router.callback_query(F.data == "cancel_search", SearchStates.searching)
async def cancel_search(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    cancel_event = cancel_events.get(user_id)
    if cancel_event:
        cancel_event.set()
        logging.info(f"Пользователь {user_id} отменил поиск")

    # 🆕 Удаляем предыдущее сообщение
    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer("❌ Поиск отменен.", reply_markup=get_main_keyboard())
    cancel_events.pop(user_id, None)
    await state.clear()
    await callback.answer()