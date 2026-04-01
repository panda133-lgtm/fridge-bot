import sqlite3
import os
import aiosqlite

DATABASE_NAME = "./fridge.db"

async def init_db():
    conn = await aiosqlite.connect(DATABASE_NAME)
    cursor = await conn.cursor()
    await cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            quantity REAL NOT NULL,
            unit TEXT NOT NULL DEFAULT "штука"
        )
    ''')
    await conn.commit()
    await conn.close()

async def get_all_products():
    conn = await aiosqlite.connect(DATABASE_NAME)
    cursor = await conn.cursor()
    await cursor.execute('SELECT name, quantity, unit FROM products ORDER BY quantity ASC')
    products = await cursor.fetchall()
    await conn.close()
    return products

async def add_or_update_product(name, quantity, unit="штука"):
    conn = await aiosqlite.connect(DATABASE_NAME)
    cursor = await conn.cursor()
    await cursor.execute('''
        INSERT INTO products (name, quantity, unit)
        VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET quantity = excluded.quantity, unit = excluded.unit
    ''', (name, quantity, unit))
    await conn.commit()
    await conn.close()

async def change_quantity(name, amount):
    conn = await aiosqlite.connect(DATABASE_NAME)
    cursor = await conn.cursor()
    await cursor.execute('SELECT quantity, unit FROM products WHERE name = ?', (name,))
    result = await cursor.fetchone()
    
    if result:
        old_qty, unit = result
        new_qty = max(0, old_qty + amount)
        await cursor.execute('UPDATE products SET quantity = ? WHERE name = ?', (new_qty, name))
        await conn.commit()
        await conn.close()
        return new_qty
    await conn.close()
    return 0

async def delete_product(name):
    conn = await aiosqlite.connect(DATABASE_NAME)
    cursor = await conn.cursor()
    await cursor.execute('DELETE FROM products WHERE name = ?', (name,))
    await conn.commit()
    await conn.close()
