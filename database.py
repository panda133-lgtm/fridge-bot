import aiosqlite

DATABASE_NAME = "./fridge.db"

async def init_db():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                quantity REAL NOT NULL,
                unit TEXT NOT NULL DEFAULT "штука"
            )
        ''')
        await db.commit()

async def get_all_products():
    async with aiosqlite.connect(DATABASE_NAME) as db:
        async with db.execute('SELECT name, quantity, unit FROM products ORDER BY name') as cursor:
            return await cursor.fetchall()

async def add_or_update_product(name, quantity, unit="штука"):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute('''
            INSERT INTO products (name, quantity, unit)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET quantity = excluded.quantity, unit = excluded.unit
        ''', (name, float(quantity), unit))
        await db.commit()

async def change_quantity(name, amount):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute('UPDATE products SET quantity = quantity + ? WHERE name = ?', (amount, name))
        await db.commit()
        async with db.execute('SELECT quantity FROM products WHERE name = ?', (name,)) as cursor:
            result = await cursor.fetchone()
            return result[0] if result else 0

async def delete_product(name):
    async with aiosqlite.connect(DATABASE_NAME) as db:
        await db.execute('DELETE FROM products WHERE name = ?', (name,))
        await db.commit()
