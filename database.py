import os
import asyncpg

# Читаем ссылку на базу из переменных хостинга
DATABASE_URL = os.getenv("DATABASE_URL")

async def get_pool():
    """Создаёт подключение к базе (кэшируется для скорости)"""
    if not hasattr(get_pool, "_pool"):
        get_pool._pool = await asyncpg.create_pool(DATABASE_URL)
    return get_pool._pool

async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                quantity REAL NOT NULL DEFAULT 0,
                unit TEXT NOT NULL DEFAULT 'шт.'
            )
        ''')

async def get_all_products():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch('SELECT id, name, quantity, unit FROM products ORDER BY name')
        return [(row["id"], row["name"], row["quantity"], row["unit"]) for row in rows]

async def add_or_update_product(name: str, quantity: float, unit: str = "шт."):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO products (name, quantity, unit) VALUES ($1, $2, $3)
            ON CONFLICT (name) DO UPDATE SET quantity = $2, unit = $3
        ''', name, float(quantity), unit)

async def change_quantity_by_id(product_id: int, delta: float):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('UPDATE products SET quantity = quantity + $1 WHERE id = $2', delta, product_id)
        return await conn.fetchval('SELECT quantity FROM products WHERE id = $1', product_id)

async def delete_product_by_id(product_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute('DELETE FROM products WHERE id = $1', product_id)
