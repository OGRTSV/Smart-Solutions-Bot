import re

def validate_phone(phone: str) -> str | None:
    cleaned = re.sub(r'\D', '', phone)
    if cleaned.startswith('8') and len(cleaned) == 11:
        cleaned = '7' + cleaned[1:]
    if len(cleaned) == 11 and cleaned.startswith('7'):
        return f"+7{cleaned[1:]}"
    return None

def validate_fio(fio: str) -> bool:
    """Проверяет ФИО: минимум 2 слова, кириллица или латиница, дефисы разрешены."""
    parts = fio.strip().split()
    if len(parts) < 2 or len(parts) > 3:
        return False
    pattern = re.compile(r'^[А-Яа-яЁёA-Za-z\-]+$')
    return all(bool(pattern.match(part)) for part in parts)

def validate_plate(plate: str) -> str | None:
    plate_upper = plate.strip().upper()
    allowed_letters = "АВЕКМНОРСТУХ"
    pattern = re.compile(rf'^[{allowed_letters}]\d{{3}}[{allowed_letters}]{{2}}\d{{2,3}}$')
    if pattern.match(plate_upper):
        return plate_upper
    return None


def validate_github_username(username: str) -> str | None:
    """
    Валидирует никнейм GitHub.

    Правила GitHub:
    - Длина от 1 до 39 символов
    - Только латинские буквы, цифры и дефисы
    - Не может начинаться или заканчиваться дефисом
    - Не может содержать два дефиса подряд
    - Не может состоять только из цифр

    Args:
        username: Введённый никнейм

    Returns:
        str: Очищенный и валидный никнейм
        None: Если никнейм некорректный
    """
    if not username:
        return None

    # Очистка от @ в начале и пробелов
    cleaned = username.strip().lstrip("@").lower()

    # Проверка длины
    if len(cleaned) < 1 or len(cleaned) > 39:
        return None

    # Проверка на допустимые символы (только латиница, цифры, дефис)
    if not re.match(r'^[a-z0-9-]+$', cleaned):
        return None

    # Запрет никнеймов, состоящих только из цифр
    # (GitHub не разрешает регистрировать чисто цифровые имена)
    if cleaned.isdigit():
        return None

    # Не может начинаться или заканчиваться дефисом
    if cleaned.startswith("-") or cleaned.endswith("-"):
        return None

    # Не может содержать два дефиса подряд
    if "--" in cleaned:
        return None

    return cleaned


import re


def validate_username(username: str) -> bool:
    """
    Проверяет корректность username.

    Правила:
    - Латинские буквы, цифры, символы . _ -
    - Длина от 3 до 30 символов
    - Не начинается и не заканчивается на . _ -
    - Не состоит только из цифр (не может быть номером телефона)
    """
    if not username:
        return False

    # Длина
    if len(username) < 3 or len(username) > 30:
        return False

    # Допустимые символы
    if not re.match(r'^[a-zA-Z0-9._-]+$', username):
        return False

    # Запрет никнеймов, состоящих только из цифр
    # (вроде практически ни одна платформа не разрешает чисто цифровые публичные имена)
    if username.isdigit():
        return False

    # Не начинается и не заканчивается на специальные символы
    if username[0] in '._-' or username[-1] in '._-':
        return False

    return True