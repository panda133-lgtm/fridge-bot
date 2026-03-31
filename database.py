import aiosqlite

DB_NAME = 'fridge.db'


async def init_db():
    """Создает таблицу при первом запуске"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                quantity INTEGER DEFAULT 0
            )
        ''')
        await db.commit()


async def get_all_products():
    """Возвращает список всех продуктов"""
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute('SELECT name, quantity FROM products ORDER BY quantity ASC') as cursor:
            return await cursor.fetchall()


async def add_or_update_product(name: str, quantity: int):
    """Добавляет новый продукт или обновляет количество"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT quantity FROM products WHERE name = ?', (name,))
        exists = await cursor.fetchone()

        if exists:
            await db.execute('UPDATE products SET quantity = ? WHERE name = ?', (quantity, name))
        else:
            await db.execute('INSERT INTO products (name, quantity) VALUES (?, ?)', (name, quantity))
        await db.commit()


async def change_quantity(name: str, delta: int):
    """Изменяет количество на указанное число (+1 или -1)"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT quantity FROM products WHERE name = ?', (name,))
        result = await cursor.fetchone()

        if result:
            new_qty = result[0] + delta
            if new_qty < 0:
                new_qty = 0

            await db.execute('UPDATE products SET quantity = ? WHERE name = ?', (new_qty, name))
            await db.commit()
            return new_qty
    return None


async def delete_product(name: str):
    """Удаляет продукт из списка"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('DELETE FROM products WHERE name = ?', (name,))
        await db.commit()