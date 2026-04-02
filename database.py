import aiosqlite

DB_NAME = "fridge.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT "шт."
            )
        ''')
        await db.commit()

async def get_all_products():
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT id, name, quantity, unit FROM products ORDER BY name') as cur:
            return await cur.fetchall()

async def add_or_update_product(name, qty, unit="шт."):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            INSERT INTO products (name, quantity, unit) VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET quantity = excluded.quantity, unit = excluded.unit
        ''', (name, float(qty), unit))
        await db.commit()

async def change_quantity(name, delta):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE products SET quantity = quantity + ? WHERE name = ?', (delta, name))
        await db.commit()
        async with db.execute('SELECT quantity FROM products WHERE name = ?', (name,)) as cur:
            result = await cur.fetchone()
            return result[0] if result else 0

async def delete_product(name):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM products WHERE name = ?', (name,))
        await db.commit()

# === НОВЫЕ ФУНКЦИИ (добавь только это!) ===
async def change_quantity_by_id(product_id, delta):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('UPDATE products SET quantity = quantity + ? WHERE id = ?', (delta, product_id))
        await db.commit()

async def delete_product_by_id(product_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM products WHERE id = ?', (product_id,))
        await db.commit()
