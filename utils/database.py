"""
database.py - Модуль для работы с базой данных SQLite
Содержит модели, функции создания таблиц и операции CRUD
"""

import sqlite3
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Путь к файлу базы данных
DB_PATH = "osint_bot.db"


def init_database():
    """
    Инициализирует базу данных: создаёт таблицы, если они не существуют.
    Вызывается при запуске бота.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Таблица пользователей
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                first_name TEXT,
                registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT 1,
                role TEXT DEFAULT 'user',
                requests_limit INTEGER DEFAULT 10,
                requests_today INTEGER DEFAULT 0,
                last_request_date DATE DEFAULT CURRENT_DATE
            )
        """)

        # Таблица запросов (история)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                search_type TEXT NOT NULL,
                search_value TEXT NOT NULL,
                source TEXT,
                status TEXT DEFAULT 'pending',
                results_count INTEGER DEFAULT 0,
                execution_time_ms INTEGER,
                results_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Таблица кэша результатов
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_type TEXT NOT NULL,
                search_value TEXT NOT NULL,
                source TEXT NOT NULL,
                results_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                UNIQUE(search_type, search_value, source)
            )
        """)

        # Таблица логов ошибок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER,
                error_type TEXT NOT NULL,
                error_message TEXT,
                source TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES requests(id)
            )
        """)

        conn.commit()
        conn.close()
        logger.info("✅ База данных успешно инициализирована")

    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")
        raise


def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None) -> int:
    """
    Получает ID пользователя из БД или создаёт нового.

    Args:
        telegram_id: Telegram ID пользователя
        username: Имя пользователя в Telegram
        first_name: Имя пользователя

    Returns:
        int: ID пользователя в базе данных
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Проверяем, существует ли пользователь
        cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (telegram_id,))
        result = cursor.fetchone()

        if result:
            user_id = result[0]
            # Обновляем username и first_name, если они изменились
            cursor.execute("""
                UPDATE users SET username = ?, first_name = ?
                WHERE id = ?
            """, (username, first_name, user_id))
        else:
            # Создаём нового пользователя
            cursor.execute("""
                INSERT INTO users (telegram_id, username, first_name)
                VALUES (?, ?, ?)
            """, (telegram_id, username, first_name))
            user_id = cursor.lastrowid
            logger.info(f"Создан новый пользователь: {telegram_id} ({username})")

        conn.commit()
        conn.close()
        return user_id

    except Exception as e:
        logger.error(f"Ошибка получения/создания пользователя: {e}")
        raise


def create_request(user_id: int, search_type: str, search_value: str, source: str = None) -> int:
    """
    Создаёт новую запись о запросе в БД.

    Args:
        user_id: ID пользователя в БД
        search_type: Тип поиска ('phone', 'fio', 'plate')
        search_value: Искомое значение
        source: Источник данных

    Returns:
        int: ID созданного запроса
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # 🆕 Используем локальное время Python
        current_time = datetime.now().isoformat()

        cursor.execute("""
                INSERT INTO requests (user_id, search_type, search_value, source, status, created_at)
                VALUES (?, ?, ?, ?, 'processing', ?)
            """, (user_id, search_type, search_value, source, current_time))

        request_id = cursor.lastrowid
        conn.commit()
        conn.close()

        logger.info(f"Создан запрос #{request_id}: {search_type}={search_value}")
        return request_id

    except Exception as e:
        logger.error(f"Ошибка создания запроса: {e}")
        raise


def update_request_success(request_id: int, results: List[Dict], execution_time_ms: int):
    """
    Обновляет запрос после успешного выполнения.

    Args:
        request_id: ID запроса
        results: Список результатов поиска
        execution_time_ms: Время выполнения в миллисекундах
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        results_json = json.dumps(results, ensure_ascii=False)
        # 🆕 Используем локальное время Python
        completed_time = datetime.now().isoformat()

        cursor.execute("""
                UPDATE requests 
                SET status = 'completed',
                    results_count = ?,
                    execution_time_ms = ?,
                    results_json = ?,
                    completed_at = ?
                WHERE id = ?
            """, (len(results), execution_time_ms, results_json, completed_time, request_id))

        conn.commit()
        conn.close()
        logger.info(f"Запрос #{request_id} успешно завершён, найдено {len(results)} записей")

    except Exception as e:
        logger.error(f"Ошибка обновления запроса: {e}")
        raise


def update_request_error(request_id: int, error_type: str, error_message: str):
    """
    Обновляет запрос при ошибке или отмене.

    Args:
        request_id: ID запроса
        error_type: Тип ошибки ('cancelled', 'not_found', 'parser_error', 'error' и др.)
        error_message: Текст ошибки
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Маппим тип ошибки в корректный статус
        # Отмена и специфичные типы сохраняются как есть,
        # всё остальное становится обычной ошибкой 'error'
        status_mapping = {
            'cancelled': 'cancelled',  # Отмена пользователем
            'not_found': 'not_found',  # Не найдено (404)
            'parser_error': 'parser_error'  # Ошибка парсинга
        }
        status = status_mapping.get(error_type, 'error')

        cursor.execute("""
            UPDATE requests 
            SET status = ?, completed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, request_id))

        # Логируем ошибку (только для настоящих ошибок, не для отмен)
        if error_type != 'cancelled':
            cursor.execute("""
                INSERT INTO error_log (request_id, error_type, error_message)
                VALUES (?, ?, ?)
            """, (request_id, error_type, error_message))

        conn.commit()
        conn.close()

        # Разные уровни логирования для разных типов
        if error_type == 'cancelled':
            logger.info(f"Запрос #{request_id} отменён пользователем")
        else:
            logger.warning(f"Запрос #{request_id} завершился с ошибкой: {error_type} — {error_message}")

    except Exception as e:
        logger.error(f"Ошибка обновления запроса с ошибкой: {e}")
        raise


def get_user_history(telegram_id: int, limit: int = 10, offset: int = 0) -> List[Dict]:
    """
    Получает историю запросов пользователя с поддержкой пагинации.

    Args:
        telegram_id: Telegram ID пользователя
        limit: Максимальное количество записей
        offset: Смещение для пагинации

    Returns:
        List[Dict]: Список запросов пользователя
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT r.id, r.search_type, r.search_value, r.source, r.status,
                   r.results_count, r.created_at
            FROM requests r
            JOIN users u ON r.user_id = u.id
            WHERE u.telegram_id = ?
            ORDER BY r.created_at DESC
            LIMIT ? OFFSET ?
        """, (telegram_id, limit, offset))

        rows = cursor.fetchall()
        conn.close()

        history = []
        for row in rows:
            history.append({
                'request_id': row[0],
                'search_type': row[1],
                'search_value': row[2],
                'source': row[3],
                'status': row[4],
                'results_count': row[5],
                'created_at': row[6]
            })

        return history

    except Exception as e:
        logger.error(f"Ошибка получения истории: {e}")
        return []


def get_request_results(request_id: int) -> Optional[Dict]:
    """
    Получает результаты запроса из БД.

    Args:
        request_id: ID запроса

    Returns:
        Dict с результатами или None
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT search_type, search_value, source, results_json, created_at, status
            FROM requests
            WHERE id = ?
        """, (request_id,))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            'search_type': row[0],
            'search_value': row[1],
            'source': row[2],
            'results': json.loads(row[3]) if row[3] else [],
            'created_at': row[4],
            'status': row[5]
        }

    except Exception as e:
        logger.error(f"Ошибка получения результатов запроса: {e}")
        return None


def check_cache(search_type: str, search_value: str, source: str) -> Optional[List[Dict]]:
    """
    Проверяет наличие результатов в кэше.

    Args:
        search_type: Тип поиска
        search_value: Искомое значение
        source: Источник

    Returns:
        Результаты из кэша или None
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT results_json, expires_at
            FROM cache
            WHERE search_type = ? AND search_value = ? AND source = ?
        """, (search_type, search_value, source))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Проверяем, не истёк ли кэш
        if row[1]:
            expires_at = datetime.fromisoformat(row[1])
            if datetime.now() > expires_at:
                return None

        return json.loads(row[0])

    except Exception as e:
        logger.error(f"Ошибка проверки кэша: {e}")
        return None


def save_to_cache(search_type: str, search_value: str, source: str, results: List[Dict], cache_days: int = 30):
    """
    Сохраняет результаты в кэш (заменяет старые данные при наличии).

    Args:
        search_type: Тип поиска
        search_value: Искомое значение
        source: Источник
        results: Результаты поиска
        cache_days: Срок хранения кэша в днях (по умолчанию 30)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        results_json = json.dumps(results, ensure_ascii=False)
        expires_at = (datetime.now() + timedelta(days=cache_days)).isoformat()
        # 🆕 Используем локальное время Python
        created_at = datetime.now().isoformat()

        # Удаляем старую запись
        cursor.execute("""
                DELETE FROM cache 
                WHERE search_type = ? AND search_value = ? AND source = ?
            """, (search_type, search_value, source))

        # Вставляем новую с локальным временем
        cursor.execute("""
                INSERT INTO cache 
                (search_type, search_value, source, results_json, expires_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (search_type, search_value, source, results_json, expires_at, created_at))

        conn.commit()
        conn.close()
        logger.info(f"Результаты сохранены в кэш: {search_type}={search_value} (срок: {cache_days} дней)")

    except Exception as e:
        logger.error(f"Ошибка сохранения в кэш: {e}")



def check_user_limit(telegram_id: int) -> tuple[bool, int]:
    """
    Проверяет, не превысил ли пользователь лимит запросов.

    Args:
        telegram_id: Telegram ID пользователя

    Returns:
        (можно_ли_делать_запрос, оставшийся_лимит)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT requests_limit, requests_today, last_request_date
            FROM users
            WHERE telegram_id = ?
        """, (telegram_id,))

        row = cursor.fetchone()
        if not row:
            conn.close()
            return True, 10

        limit, today_count, last_date = row
        today = datetime.now().date().isoformat()

        # Если день изменился, сбрасываем счётчик
        if last_date != today:
            cursor.execute("""
                UPDATE users SET requests_today = 0, last_request_date = ?
                WHERE telegram_id = ?
            """, (today, telegram_id))
            conn.commit()
            today_count = 0

        conn.close()

        if today_count >= limit:
            return False, 0

        return True, limit - today_count

    except Exception as e:
        logger.error(f"Ошибка проверки лимита: {e}")
        return True, 10


def increment_user_requests(telegram_id: int):
    """Увеличивает счётчик запросов пользователя."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        today = datetime.now().date().isoformat()

        cursor.execute("""
            UPDATE users 
            SET requests_today = requests_today + 1, last_request_date = ?
            WHERE telegram_id = ?
        """, (today, telegram_id))

        conn.commit()
        conn.close()

    except Exception as e:
        logger.error(f"Ошибка увеличения счётчика запросов: {e}")


def get_cache_date(search_type: str, search_value: str, source: str) -> Optional[str]:
    """
    Получает дату создания кэша.

    Args:
        search_type: Тип поиска
        search_value: Искомое значение
        source: Источник

    Returns:
        Дата создания кэша в формате YYYY-MM-DD или None
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT created_at
            FROM cache
            WHERE search_type = ? AND search_value = ? AND source = ?
        """, (search_type, search_value, source))

        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        # Извлекаем только дату (YYYY-MM-DD)
        return row[0][:10]

    except Exception as e:
        logger.error(f"Ошибка получения даты кэша: {e}")
        return None