from aiogram import Router, F, types
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from utils.keyboards import get_main_keyboard
from utils.database import get_or_create_user

router = Router()


@router.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()

    # Регистрируем или обновляем пользователя в базе данных
    get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name
    )

    await message.answer("👋 Добро пожаловать в OSINT-бот компании «Умные решения»!")
    await message.answer(
        f"🔍 Выберите тип поиска из меню ниже.\n\n"
        f"Вы можете посмотреть историю запросов, введя команду /history в любой момент.",
        reply_markup=get_main_keyboard()
    )

@router.message(F.text)
async def handle_other_messages(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Я не совсем понял команду. Пожалуйста, используйте кнопку /start или выберите действие из меню:",
        reply_markup=get_main_keyboard()
    )