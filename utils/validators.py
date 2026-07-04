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

    Args:
        username: Введённый никнейм

    Returns:
        str: Очищенный и валидный никнейм
        None: Если никнейм некорректный
    """
    if not username:
        return None

    # Очищаем от @ в начале и пробелов
    cleaned = username.strip().lstrip("@").lower()

    # Проверяем длину
    if len(cleaned) < 1 or len(cleaned) > 39:
        return None

    # Проверяем на допустимые символы (только латиница, цифры, дефис)
    if not re.match(r'^[a-z0-9-]+$', cleaned):
        return None

    # Не может начинаться или заканчиваться дефисом
    if cleaned.startswith("-") or cleaned.endswith("-"):
        return None

    # Не может содержать два дефиса подряд
    if "--" in cleaned:
        return None

    return cleaned