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

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)  # ✅ ПОПРАВИЛ ОШИБКУ
dp = Dispatcher()

# Машина состояний
class AddProduct(StatesGroup):
    name = State()
    quantity = State()

# Пагинация — показываем максимум 15 продуктов за раз
PRODUCTS_PER_PAGE = 15
user_state = {}  # Сохраняем список для каждого пользователя

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
    global user_state
    
    products = await database.get_all_products()
    
    if not products:
        await message.answer("Холодильник пуст! Добавьте что-нибудь.")
        return
    
    # Сохраняем состояние пользователя
    user_id = message.from_user.id
    user_state[user_id] = {'products': products}
    
    # Показываем первую страницу
    await show_page(user_id, page=1, original_message=message)

# Вспомогательная функция для показа страницы
async def show_page(user_id, page=None, original_message=None):
    global user_state
    
    if user_id not in user_state:
        products = await database.get_all_products()
        user_state[user_id] = {'products': products}
    
    data = user_state[user_id]
    products = data['products']
    
    current_page = page if page is not None else 1
    total_pages = (len(products) + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    
    if current_page < 1:
        current_page = 1
    elif current_page > total_pages:
        current_page = total_pages
    
    start = (current_page - 1) * PRODUCTS_PER_PAGE
    end = min(start + PRODUCTS_PER_PAGE, len(products))
    page_products = products[start:end]
    
    text = f"📋 **Список ({current_page}/${total_pages}):**\n\n"
    for i, (name, qty) in enumerate(page_products):
        icon = "⚠️" if qty < 3 else "✅"
        text += f"{icon} `{name}`: {qty} шт.\n"
    
    text += "\n💡 Используй кнопки ниже ⬅️➡️"
    
    keyboard = []
    if total_pages > 1:
        row = []
        if current_page > 1:
            row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"prev_{current_page-1}_{user_id}"))
        if current_page < total_pages:
            row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"next_{current_page+1}_{user_id}"))
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_list")])
    
    reply_markup = InlineKeyboardMarkup(inline_keyboard=keyboard)
    
    try:
        if original_message:
            await original_message.edit_text(
                text, 
                parse_mode="Markdown",
                reply_markup=reply_markup
            )
    except Exception as e:
        print(f"Ошибка редактирования: {e}")

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
        await show_updated_list(callback.message, callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")
        logging.error(f"Increase error: {e}")

@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, -1)
        await callback.answer(f"{name}: {new_qty}")
        await show_updated_list(callback.message, callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")
        logging.error(f"Decrease error: {e}")

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        await database.delete_product(name)
        await callback.answer(f"{name} удален")
        await show_updated_list(callback.message, callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}")
        logging.error(f"Delete error: {e}")

# Навигация по страницам
@dp.callback_query(F.data.startswith("prev_"))
async def prev_page(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = int(parts[1])
    user_id = int(parts[2])
    await callback.answer()
    await show_page(user_id, page, original_message=callback.message)

@dp.callback_query(F.data.startswith("next_"))
async def next_page(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = int(parts[1])
    user_id = int(parts[2])
    await callback.answer()
    await show_page(user_id, page, original_message=callback.message)

@dp.callback_query(F.data == "refresh_list")
async def refresh_list(callback: types.CallbackQuery):
    await callback.answer()
    await show_updated_list(callback.message, callback.from_user.id)

# Показ обновлённого списка
async def show_updated_list(message, user_id):
    products = await database.get_all_products()
    
    if not products:
        await message.answer("Холодильник пуст!")
        return
    
    # Всегда используем пагинацию — это надёжнее!
    user_state[user_id] = {'products': products}
    await show_page(user_id, page=1, original_message=message)

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
