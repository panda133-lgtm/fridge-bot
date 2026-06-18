"""
Модуль работы с базой данных (PostgreSQL)
"""
import os
import asyncpg
from datetime import datetime, timezone, timedelta

DATABASE_URL = os.getenv("DATABASE_URL")
_last_update_time = None

# Часовой пояс МСК (UTC+3)
MSK = timezone(timedelta(hours=3))

def set_last_update_time():
    """Записывает текущее время в МСК"""
    global _last_update_time
    _last_update_time = datetime.now(MSK)

def get_last_update_time():
    """Возвращает время последнего обновления или None"""
    return _last_update_time

async def init_db():
    """Создаёт таблицы products и users, если их нет"""
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL не найден!")
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    
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
    
    await conn.close()
    print("✅ Таблицы products и users готовы")

async def get_all_products():
    if not DATABASE_URL:
        return []
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch('SELECT id, name, quantity, unit FROM products ORDER BY name')
    await conn.close()
    return [(row["id"], row["name"], row["quantity"], row["unit"]) for row in rows]

async def add_or_update_product(name: str, quantity: float, unit: str = "шт."):
    if not DATABASE_URL:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        INSERT INTO products (name, quantity, unit) VALUES ($1, $2, $3)
        ON CONFLICT (name) DO UPDATE SET quantity = $2, unit = $3
    ''', name, float(quantity), unit)
    await conn.close()

async def change_quantity_by_id(product_id: int, delta: float):
    if not DATABASE_URL:
        return 0
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('UPDATE products SET quantity = quantity + $1 WHERE id = $2', delta, product_id)
    result = await conn.fetchval('SELECT quantity FROM products WHERE id = $1', product_id)
    await conn.close()
    return result

async def delete_product_by_id(product_id: int):
    if not DATABASE_URL:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('DELETE FROM products WHERE id = $1', product_id)
    await conn.close()

async def save_user_chat_id(chat_id: int):
    if not DATABASE_URL:
        return
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('INSERT INTO users (chat_id) VALUES ($1) ON CONFLICT (chat_id) DO NOTHING', chat_id)
    await conn.close()

async def get_all_user_chat_ids():
    if not DATABASE_URL:
        return []
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch('SELECT chat_id FROM users')
    await conn.close()
    return [row["chat_id"] for row in rows]

async def get_low_stock_products(threshold: float = 3.0):
    if not DATABASE_URL:
        return []
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(
        'SELECT name, quantity, unit FROM products WHERE quantity <= $1 ORDER BY name',
        threshold
    )
    await conn.close()
    return [(row["name"], row["quantity"], row["unit"]) for row in rows]
