from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Поиск по телефону", callback_data="search_phone")],
        [InlineKeyboardButton(text="👤 Поиск по ФИО", callback_data="search_fio")],
        [InlineKeyboardButton(text="🐙 Поиск по GitHub", callback_data="open_github_menu")],
        [InlineKeyboardButton(text="🚗 Поиск по госномеру (временно не работает)", callback_data="search_plate")],
        [InlineKeyboardButton(text="📜 История запросов", callback_data="open_history")],
    ])

def get_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏛️ ЕГРЮЛ/ЕГРИП (ФНС)", callback_data="source_fns")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_search")],
    ])

def get_phone_source_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏢 По организациям", callback_data="phone_source_listorg")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_search")],
    ])

def get_fio_navigation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_source")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])

def get_phone_navigation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_phone_source")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="cancel_search")],
    ])

def get_github_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти по нику GitHub", callback_data="github_search_username")],
        [InlineKeyboardButton(text="⚔️ Сравнить двух пользователей", callback_data="github_compare_start")],
        [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
    ])

def get_github_profile_actions(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Репозитории", callback_data=f"github_repos:{username}")],
        [InlineKeyboardButton(text="📈 Активность", callback_data=f"github_activity:{username}")],
        [InlineKeyboardButton(text="🌐 Открыть профиль", url=f"https://github.com/{username}")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])

def get_github_back_to_profile(username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад к профилю", callback_data=f"github_back_profile:{username}")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])

def get_cancel_keyboard_github() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="open_github_menu")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])

def get_github_compare_actions(username1: str, username2: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌐 Открыть профиль ({username1})", url=f"https://github.com/{username1}")],
        [InlineKeyboardButton(text=f"🌐 Открыть профиль ({username2})", url=f"https://github.com/{username2}")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")],
    ])