import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
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

# === ГЛАВНАЯ КОМАНДА ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я ваш Умный Холодильник 🧊\n"
        "Я помогу не забыть купить еду.\n"
        "Используйте кнопки внизу или пишите мне.",
        reply_markup=keyboards.get_main_menu()
    )

# Показать список (без пагинации!)
@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        await message.answer("Холодильник пуст! Добавьте что-нибудь.")
        return
    
    # Разбиваем на несколько сообщений, если продуктов много (>20)
    CHUNK_SIZE = 20
    if len(products) <= CHUNK_SIZE:
        await send_list_in_one_message(message, products)
    else:
        chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
        for i, chunk in enumerate(chunks):
            await send_list_in_one_message(message, chunk, current=i+1, total=len(chunks))
            await asyncio.sleep(0.5)  # Пауза между сообщениями

# Отправка списка продуктов
async def send_list_in_one_message(message, products, current=None, total=None):
    status_prefix = ""
    if current and total:
        status_prefix = f"({current}/${total}) "
    
    text = f"📋 **Список продуктов {status_prefix}**:\n\n"
    for name, qty in products:
        icon = "⚠️" if qty < 3 else "✅"
        text += f"{icon} `{name}`: {qty} шт.\n"
    
    # Добавляем кнопку обновить в конце каждого сообщения
    keyboard = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_list")]]
    
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
    
    await database.add_or_update_product(name, qty)
    await message.answer(f"✅ Готово! `{name}`: {qty} шт.")
    await state.clear()

# === ОБРАБОТКА КНОПОК ===
@dp.callback_query(F.data.startswith("inc_"))
async def increase_qty(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, 1)
        await callback.answer(f"{name}: {new_qty}")
        await refresh_callback(callback)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")
        logging.error(f"Increase error: {e}")

@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, -1)
        await callback.answer(f"{name}: {new_qty}")
        await refresh_callback(callback)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")
        logging.error(f"Decrease error: {e}")

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        await database.delete_product(name)
        await callback.answer(f"{name} удален")
        await refresh_callback(callback)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")
        logging.error(f"Delete error: {e}")

@dp.callback_query(F.data == "refresh_list")
async def refresh_list(callback: types.CallbackQuery):
    await callback.answer()
    await refresh_callback(callback)

# Обновление списка по кнопке
async def refresh_callback(callback):
    products = await database.get_all_products()
    
    if not products:
        await callback.message.edit_text("Холодильник пуст!")
        return
    
    # Разбиваем на чанки для удобного отображения
    CHUNK_SIZE = 20
    if len(products) <= CHUNK_SIZE:
        text = f"📋 **Актуальный список:**\n\n"
        for name, qty in products:
            icon = "⚠️" if qty < 3 else "✅"
            text += f"{icon} `{name}`: {qty} шт.\n"
        
        keyboard = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_list")]]
        
        await callback.message.edit_text(
            text, 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    else:
        chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
        text = f"📋 **Список (страница 1/${len(chunks)}):**\n\n"
        for name, qty in chunks[0]:
            icon = "⚠️" if qty < 3 else "✅"
            text += f"{icon} `{name}`: {qty} шт.\n"
        text += "\n💡 Используй /list чтобы увидеть весь список"
        
        keyboard = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_list")]]
        
        await callback.message.edit_text(
            text, 
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )

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
    await database.init_db()
    print("🤖 Бот запущен...")
    asyncio.create_task(start_health_server())
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
