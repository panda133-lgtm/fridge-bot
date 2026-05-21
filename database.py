"""
Модуль работы с базой данных (PostgreSQL)
"""
import os
import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    """Создаёт таблицу продуктов, если её нет"""
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
    await conn.close()
    print("✅ Таблица products готова")

async def get_all_products():
    """Возвращает все продукты: [(id, name, qty, unit), ...]"""
    if not DATABASE_URL:
        return []
    
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch('SELECT id, name, quantity, unit FROM products ORDER BY name')
    await conn.close()
    
    return [(row["id"], row["name"], row["quantity"], row["unit"]) for row in rows]

async def add_or_update_product(name: str, quantity: float, unit: str = "шт."):
    """Добавляет продукт или обновляет количество, если имя совпадает"""
    if not DATABASE_URL:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('''
        INSERT INTO products (name, quantity, unit) VALUES ($1, $2, $3)
        ON CONFLICT (name) DO UPDATE SET quantity = $2, unit = $3
    ''', name, float(quantity), unit)
    await conn.close()

async def change_quantity_by_id(product_id: int, delta: float):
    """Изменяет количество продукта по его ID"""
    if not DATABASE_URL:
        return 0
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        'UPDATE products SET quantity = quantity + $1 WHERE id = $2',
        delta, product_id
    )
    result = await conn.fetchval(
        'SELECT quantity FROM products WHERE id = $1',
        product_id
    )
    await conn.close()
    return result

async def delete_product_by_id(product_id: int):
    """Удаляет продукт по его ID"""
    if not DATABASE_URL:
        return
    
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute('DELETE FROM products WHERE id = $1', product_id)
    await conn.close()
