import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from aiohttp import web
from urllib.parse import quote, unquote

import database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- СОСТОЯНИЯ ---
class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

CHUNK_SIZE = 20
last_notification_day = None

# --- ГЛАВНОЕ МЕНЮ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = [[KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]]
    await message.answer(
        "Привет! Умный Холодильник 🧊\n\nЧто делаем?",
        reply_markup=ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
    )

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        kb = [[InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_prod")]]
        await message.answer("❌ Холодильник пуст!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    
    for chunk in chunks:
        await send_chunk(message, chunk)
    if len(chunks) > 1:
        await asyncio.sleep(0.5)

def get_main_kb():
    """Главное меню для текстовых сообщений"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]], 
        resize_keyboard=True
    )

def get_product_kb(products):
    """Клавиатура для каждого продукта"""
    keyboard = []
    for name, qty, unit in products:
        encoded = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded}"),
            InlineKeyboardButton(text=f"{name}", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="low_q")])
    keyboard.append([InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_prod")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

async def send_chunk(message, products):
    text = f"📋 **Список:**\n\n"
    for name, qty, unit in products:
        icon = "⚠️" if float(qty) <= 1 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    await message.answer(
        text, 
        parse_mode="Markdown", 
        reply_markup=get_product_kb(products)
    )

# === ДОБАВЛЕНИЕ ПРОДУКТА ===
@dp.callback_query(F.data == "add_prod")
async def start_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.edit_text("Введите название продукта:", reply_markup=get_main_kb())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    main_kb = get_main_kb()
    if not message.text.strip():
        await message.answer("⚠️ Введите название!", reply_markup=main_kb)
        return
        
    await state.update_data(name=message.text.strip())
    await message.answer("Введите количество (число):", reply_markup=main_kb)
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        val = message.text.replace(',', '.')
        float(val)
        await state.update_data(quantity=float(val))
        
        units_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука", callback_data="u_pie")],
            [InlineKeyboardButton(text="🥛 Пол-литра", callback_data="u_hal")],
            [InlineKeyboardButton(text="🧱 Пачка", callback_data="u_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка", callback_data="u_bot")],
            [InlineKeyboardButton(text="🥗 Тарелка", callback_data="u_plt")]
        ])
        
        await message.answer("Выберите единицу:", reply_markup=units_kb)
        await state.set_state(AddProduct.unit)
        
    except ValueError:
        await message.answer("❌ Неправильное число!", reply_markup=get_main_kb())

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "hal": "пол-литра", "pack": "пачка", "bot": "бутылка", "plt": "тарелка"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await callback.message.edit_text(f"✅ **Готово!** `{name}`: {qty} {unit}", reply_markup=get_main_kb())
    await state.clear()

# === ОБРАБОТКА КНОПОК ===
@dp.callback_query(F.data.startswith(("inc_", "dec_", "del_", "refresh", "low_q")))
async def handle_buttons(callback: types.CallbackQuery):
    try:
        data = callback.data
        
        if data.startswith("inc_"):
            name = unquote(data.split("_")[1])
            new_qty = await database.change_quantity(name, 1)
            await callback.answer(f"✓ {name}: {new_qty}")
            await refresh_list(callback.from_user.id)
            
        elif data.startswith("dec_"):
            name = unquote(data.split("_")[1])
            new_qty = await database.change_quantity(name, -1)
            await callback.answer(f"✓ {name}: {new_qty}")
            await refresh_list(callback.from_user.id)
            
        elif data.startswith("del_"):
            name = unquote(data.split("_")[1])
            await database.delete_product(name)
            await callback.answer(f"✓ Удален")
            await refresh_list(callback.from_user.id)
            
        elif data == "refresh":
            await callback.answer("Обновляю...")
            await refresh_list(callback.from_user.id)
            
        elif data == "low_q":
            await callback.answer("Показываю мало...")
            await show_low_products(callback.from_user.id)
            
    except Exception as e:
        logging.error(f"Кнопка ошибка: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

async def show_low_products(user_id):
    products = await database.get_all_products()
    low = [(n, q, u) for n, q, u in products if float(q) <= 1]
    
    if not low:
        kb = [[InlineKeyboardButton(text="🔙 Назад", callback_data="refresh")]]
        await bot.send_message(chat_id=user_id, text="✅ Всё ок!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    text = "📉 **Мало осталось:**\n\n"
    for name, qty, unit in low:
        text += f"⚠️ `{name}`: {qty} {unit}\n"
    
    keyboard = []
    for name, qty, unit in low:
        encoded = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded}"),
            InlineKeyboardButton(text=f"{name}", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="refresh")])
    keyboard.append([InlineKeyboardButton(text="➕ Добавить", callback_data="add_prod")])
    
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

async def refresh_list(user_id):
    products = await database.get_all_products()
    if not products:
        return
    
    first = products[:CHUNK_SIZE]
    text = f"📋 **Список:**\n\n"
    for name, qty, unit in first:
        icon = "⚠️" if float(qty) <= 1 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    keyboard = []
    for name, qty, unit in first:
        encoded = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded}"),
            InlineKeyboardButton(text=f"{name}", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="low_q")])
    keyboard.append([InlineKeyboardButton(text="➕ Добавить", callback_data="add_prod")])
    
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

# === УВЕДОМЛЕНИЯ ===
async def notification_worker():
    global last_notification_day
    hours = [11, 16, 16]  
    minutes = ["00", "00", "30"]  
    
    while True:
        try:
            now = datetime.now()
            for idx, check_hour in enumerate(hours):
                target_min = minutes[idx]
                if now.hour == check_hour and now.minute >= int(target_min):
                    if now.day != last_notification_day:
                        last_notification_day = now.day
                        try:
                            await check_notifications()
                        except Exception as e:
                            logging.error(f"Уведомление ошибка: {e}")
                    break
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"Цикл уведомления ошибка: {e}")

async def check_notifications():
    try:
        products = await database.get_all_products()
        low = [(n, q, u) for n, q, u in products if float(q) <= 1]
        
        if not low:
            return
        
        now = datetime.now().strftime("%H:%M")
        text = f"⚠️ *НАПОМИНАНИЕ* ⚠️\n\n⏰ Время: {now}\n\n📉 *Осталось мало:* \n"
        
        for name, qty, unit in low:
            text += f"• `{name}`: {qty} {unit}\n"
        
        text += "\n🛒 Пора купить!"
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        logging.info(f"Уведомление отправлено")
    except Exception as e:
        logging.error(f"Ошибка уведомлений: {e}")

# === ЗАПУСК ===
async def main():
    try:
        await database.init_db()
        print("База готова")
    except Exception as e:
        print(f"Ошибка базы: {e}")
    
    print("🤖 Запущен!")
    asyncio.create_task(notification_worker())
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Выключен")
