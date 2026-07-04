import asyncio
from aiogram import Router, types
from aiogram.fsm.context import FSMContext

from states import SearchStates
from utils.validators import validate_plate
from utils.keyboards import get_main_keyboard

router = Router()

@router.message(SearchStates.waiting_for_plate)
async def process_plate_input(message: types.Message, state: FSMContext):
    valid_plate = validate_plate(message.text)
    if not valid_plate:
        await message.answer("❌ Неверный формат госномера. Допустимые форматы: А000АА00 или А000АА000 (используйте только буквы А, В, Е, К, М, Н, О, Р, С, Т, У, Х).")
        return

    await message.answer(f"✅ Госномер принят: `{valid_plate}`\n⏳ Запускаю поиск...", parse_mode="Markdown")
    await state.clear()
    await asyncio.sleep(3)
    await message.answer(
        f"📊 *Результаты поиска по госномеру: {valid_plate}*\n"
        "🔹 Номерограм: Найдено 2 фотографии автомобиля\n"
        "🔹 Реестр залогов: Автомобиль не находится в залоге\n"
        "🔹 ДТП: За последние 3 года не числится",
        parse_mode="Markdown"
    )
    await message.answer("🔍 Выберите тип поиска из меню ниже:", reply_markup=get_main_keyboard())