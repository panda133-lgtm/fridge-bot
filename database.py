"""
Модуль работы с базой данных (PostgreSQL)
С connection pool для стабильной работы
"""
import os
import asyncpg
from datetime import datetime, timezone, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")
_last_update_time = None
_pool = None  # Connection pool для стабильности

# Часовой пояс МСК (UTC+3)
MSK = timezone(timedelta(hours=3))

def set_last_update_time():
    """Записывает текущее время в МСК"""
    global _last_update_time
    _last_update_time = datetime.now(MSK)

def get_last_update_time():
    """Возвращает время последнего обновления или None"""
    return _last_update_time

async def get_pool():
    """Возвращает пул соединений (создаёт при первом вызове)"""
    global _pool
    if _pool is None and DATABASE_URL:
        try:
            _pool = await asyncpg.create_pool(
                DATABASE_URL,
                min_size=1,
                max_size=5,
                command_timeout=60,
            )
            print("✅ Connection pool создан")
        except Exception as e:
            print(f"⚠️ Не удалось создать pool: {e}")
            _pool = None
    return _pool

async def init_db():
    """Создаёт таблицы products и users"""
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL не найден!")
        return
    
    pool = await get_pool()
    if not pool:
        print("⚠️ Нет подключения к базе!")
        return
    
    try:
        async with pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id SERIAL PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    quantity REAL NOT NULL DEFAULT 0,
                    unit TEXT NOT NULL DEFAULT 'шт.'
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    chat_id BIGINT PRIMARY KEY,
                    added_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            print("✅ Таблицы products и users готовы")
    except Exception as e:
        print(f"⚠️ Ошибка инициализации БД: {e}")

async def get_all_products():
    """Возвращает все продукты"""
    pool = await get_pool()
    if not pool:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT id, name, quantity, unit FROM products ORDER BY name')
            return [(row["id"], row["name"], row["quantity"], row["unit"]) for row in rows]
    except Exception as e:
        print(f"⚠️ Ошибка чтения продуктов: {e}")
        return []

async def add_or_update_product(name: str, quantity: float, unit: str = "шт."):
    """Добавляет или обновляет продукт"""
    pool = await get_pool()
    if not pool:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO products (name, quantity, unit) VALUES ($1, $2, $3)
                ON CONFLICT (name) DO UPDATE SET quantity = $2, unit = $3
            ''', name, float(quantity), unit)
            return True
    except Exception as e:
        print(f"⚠️ Ошибка сохранения продукта: {e}")
        return False

async def change_quantity_by_id(product_id: int, delta: float):
    """Изменяет количество продукта"""
    pool = await get_pool()
    if not pool:
        return 0
    try:
        async with pool.acquire() as conn:
            await conn.execute('UPDATE products SET quantity = quantity + $1 WHERE id = $2', delta, product_id)
            result = await conn.fetchval('SELECT quantity FROM products WHERE id = $1', product_id)
            return result
    except Exception as e:
        print(f"⚠️ Ошибка изменения количества: {e}")
        return 0

async def delete_product_by_id(product_id: int):
    """Удаляет продукт"""
    pool = await get_pool()
    if not pool:
        return False
    try:
        async with pool.acquire() as conn:
            await conn.execute('DELETE FROM products WHERE id = $1', product_id)
            return True
    except Exception as e:
        print(f"⚠️ Ошибка удаления: {e}")
        return False

async def save_user_chat_id(chat_id: int):
    """Сохраняет chat_id пользователя"""
    pool = await get_pool()
    if not pool:
        return
    try:
        async with pool.acquire() as conn:
            await conn.execute('INSERT INTO users (chat_id) VALUES ($1) ON CONFLICT (chat_id) DO NOTHING', chat_id)
    except Exception as e:
        print(f"⚠️ Ошибка сохранения пользователя: {e}")

async def get_all_user_chat_ids():
    """Возвращает список всех chat_id"""
    pool = await get_pool()
    if not pool:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch('SELECT chat_id FROM users')
            return [row["chat_id"] for row in rows]
    except Exception as e:
        print(f"⚠️ Ошибка чтения пользователей: {e}")
        return []

async def get_low_stock_products(threshold: float = 3.0):
    """Возвращает продукты с низким запасом"""
    pool = await get_pool()
    if not pool:
        return []
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT name, quantity, unit FROM products WHERE quantity <= $1 ORDER BY name',
                threshold
            )
            return [(row["name"], row["quantity"], row["unit"]) for row in rows]
    except Exception as e:
        print(f"⚠️ Ошибка чтения низкого запаса: {e}")
        return []
