import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiohttp import web
from urllib.parse import quote, unquote

# Импорт наших модулей
import database
import keyboards

# Загрузка переменных из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env!")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Машина состояний
class AddProduct(StatesGroup):
    name = State()
    quantity = State()

# Размер чанка для разбивки списка
CHUNK_SIZE = 20

# === ГЛАВНАЯ КОМАНДА ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я ваш Умный Холодильник 🧊\n"
        "Я помогу не забыть купить еду.\n"
        "Используйте кнопки внизу или пишите мне.",
        reply_markup=keyboards.get_main_menu()
    )

# Показать список
@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        # Отправляем одно сообщение — без дублей
        text = f"❌ Холодильник пуст! Добавьте что-нибудь."
        keyboard = [[InlineKeyboardButton(text="➕ Добавить вручную", callback_data="add_manual")]]
        await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    
    # Ограничиваем количество сообщений в одном цикле
    for i, chunk in enumerate(chunks[:5]):  # Только первые 5 чанков за раз
        await send_list_chunk(message, chunk, current=i+1, total=len(chunks))
    
    # Если есть ещё чанки, отправим их через паузу
    if len(chunks) > 5:
        await asyncio.sleep(1.5)
        for chunk in chunks[5:]:
            await send_list_chunk(message, chunk)

# Отправка одного куска списка
async def send_list_chunk(message, products, current=None, total=None):
    status_prefix = ""
    if current and total:
        status_prefix = f"[{current}/{total}] "
    
    text = f"📋 **Список продуктов {status_prefix}**:\n\n"
    for name, qty in products:
        icon = "⚠️" if qty <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} шт.\n"
    
    keyboard = []
    for name, qty in products:
        encoded_name = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
            InlineKeyboardButton(text=f"{name} ({qty})", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
    
    await message.answer(
        text, 
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

# Добавить продукт
@dp.message(Command("add"))
@dp.message(F.text == "➕ Добавить вручную")
async def start_add_process(message: types.Message, state: FSMContext):
    await message.answer("Напиши название продукта (например: Молоко):")
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Теперь напиши количество (числом):")
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введи число!")
        return
    
    data = await state.get_data()
    name = data['name']
    qty = int(message.text)
    
    # Добавляем продукт синхронно
    await database.add_or_update_product(name, qty)
    await message.answer(f"✅ Готово! `{name}`: {qty} шт.")
    await state.clear()

# === ОБРАБОТКА КНОПОК ===

# Общий обработчик изменений
async def handle_quantity_change(callback, operation, amount):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, amount)
        await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
        
        # Обслуживаем обновление без дубликатов
        await refresh_last_message(callback.from_user.id, callback.message)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        logging.error(f"Operation error: {e}")

@dp.callback_query(F.data.startswith("inc_"))
async def increase_qty(callback: types.CallbackQuery):
    await handle_quantity_change(callback, 'inc', 1)

@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    await handle_quantity_change(callback, 'dec', -1)

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        await database.delete_product(name)
        await callback.answer(f"✓ {name} удален", show_alert=False)
        
        await refresh_last_message(callback.from_user.id, callback.message)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        logging.error(f"Delete error: {e}")

# Сохранение ID последнего сообщения от пользователя
user_last_messages = {}

@dp.callback_query(F.data == "refresh_list")
async def refresh_list(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last_message(callback.from_user.id, callback.message)

# Обновление списка (общая функция)
async def refresh_last_message(user_id, last_message=None):
    try:
        # Небольшая пауза перед обновлением, чтобы избежать конфликтов
        await asyncio.sleep(0.1)
        
        products = await database.get_all_products()
        
        if not products:
            msg_data = user_last_messages.get(user_id)
            if msg_data:
                try:
                    await bot.edit_message_text(
                        chat_id=msg_data["chat_id"],
                        message_id=msg_data["message_id"],
                        text="❌ Холодильник пуст! Добавьте продукты.",
                        parse_mode="Markdown"
                    )
                except:
                    pass
            return
        
        chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
        first_chunk = chunks[0]
        
        text = f"📋 **Актуальный список:**\n\n"
        for name, qty in first_chunk:
            icon = "⚠️" if qty <= 3 else "✅"
            text += f"{icon} `{name}`: {qty} шт.\n"
        
        if len(products) > CHUNK_SIZE:
            text += f"\n💡 Всего: {len(products)} продуктов (показаны первые 20)"
        
        keyboard = []
        for name, qty in first_chunk:
            encoded_name = quote(name)
            row = [
                InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
                InlineKeyboardButton(text=f"{name} ({qty})", callback_data="info"),
                InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
                InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
            ]
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
        
        msg_data = user_last_messages.get(user_id)
        if msg_data and last_message:
            await bot.edit_message_text(
                chat_id=msg_data["chat_id"],
                message_id=msg_data["message_id"],
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
        elif last_message:
            await last_message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
                
    except Exception as e:
        print(f"Ошибка при обновлении: {e}")

# === HEALTH CHECK ===
async def health_handler(request):
    return web.Response(text="OK")

async def start_health_server():
    app = web.Application()
    app.add_routes([web.get('/', health_handler)])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    print("✅ Health server started on port 8080")

# === ЗАПУСК ===
async def main():
    # Проверяем базу данных сразу при старте
    try:
        await database.init_db()
        print("База данных готова")
    except Exception as e:
        print(f"Ошибка базы данных: {e}")
        print("Бот будет работать без сохранения данных")
    
    print("🤖 Бот запущен...")
    asyncio.create_task(start_health_server())
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
