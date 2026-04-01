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
    raise ValueError("BOT_TOKEN не найден!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

CHUNK_SIZE = 20
last_notification_day = None

def get_main_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]], 
        resize_keyboard=True
    )

async def send_chunk(message, products):
    text = f"📋 **Список:**\n\n"
    for name, qty, unit in products:
        icon = "⚠️" if float(qty) <= 1 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    kb = []
    for name, qty, unit in products:
        encoded = quote(name)
        kb.append([InlineKeyboardButton(text=f"➖ {name} ➕", callback_data=f"d_{encoded}")])
    
    kb.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="r")],
        [InlineKeyboardButton(text="📉 Мало", callback_data="l")],
        [InlineKeyboardButton(text="➕ Добавить", callback_data="a")]
    ])
    
    await message.answer(
        text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)  # ✅ ИСПРАВЛЕНО!
    )

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    if not products:
        await message.answer(
            "❌ Пуст!", 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton("➕ Добавить", callback_data="a")]])  # ✅ ИСПРАВЛЕНО!
        )
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    for chunk in chunks:
        await send_chunk(message, chunk)
    if len(chunks) > 1:
        await asyncio.sleep(0.5)

@dp.callback_query(F.data == "a")
async def add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    msg = await callback.message.reply("Название продукта:", reply_markup=get_main_kb())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    if not message.text.strip():
        await message.answer("⚠️ Введите название!", reply_markup=get_main_kb())
        return
    await state.update_data(name=message.text.strip())
    await message.answer("Количество (число):", reply_markup=get_main_kb())
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(quantity=val)
        kb = InlineKeyboardMarkup(inline_keyboard=[  # ✅ ИСПРАВЛЕНО!
            [InlineKeyboardButton("🍏 Штука", callback_data="u_pie")],
            [InlineKeyboardButton("🥛 Пол-литра", callback_data="u_hal")],
            [InlineKeyboardButton("🧱 Пачка", callback_data="u_pack")],
            [InlineKeyboardButton("🍶 Бутылка", callback_data="u_bot")],
            [InlineKeyboardButton("🥗 Тарелка", callback_data="u_plt")]
        ])
        await message.answer("Выберите единицу:", reply_markup=kb)
        await state.set_state(AddProduct.unit)
    except ValueError:
        await message.answer("❌ Число!", reply_markup=get_main_kb())

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "hal": "пол-литра", "pack": "пачка", "bot": "бутылка", "plt": "тарелка"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await callback.message.delete()
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ `{name}`: {qty} {unit}")
    await state.clear()

@dp.callback_query(F.data.startswith("d_"))
async def change_qty(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_")[1])
        new_qty = await database.change_quantity(name, 0)
        await callback.answer(f"✓ {name}", show_alert=False)
        await refresh_last(callback.from_user.id)
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("r"))
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "l")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query()
async def any_callback(callback: types.CallbackQuery):
    await callback.answer("❌ Кнопка недоступна", show_alert=True)

async def show_low(user_id):
    products = await database.get_all_products()
    low = [(n, q, u) for n, q, u in products if float(q) <= 1]
    
    if not low:
        await bot.send_message(chat_id=user_id, text="✅ Всё ок!")
        return
    
    text = "📉 **Мало:**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n, q, _ in low)
    
    kb = [[InlineKeyboardButton(text=f"{n} ({q})", callback_data=f"d_{quote(n)}")] for n, q, _ in low]
    kb.append([InlineKeyboardButton("🔙 Назад", callback_data="r")])
    
    await bot.send_message(
        chat_id=user_id, 
        text=text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)  # ✅ ИСПРАВЛЕНО!
    )

async def refresh_last(user_id):
    products = await database.get_all_products()
    if not products: return
    first = products[:CHUNK_SIZE]
    text = f"📋 **Список:**\n\n" + "\n".join(f"{'⚠️' if float(q)<=1 else '✅'} `{n}`: {q} {u}" for n, q, u in first)
    
    kb = [[InlineKeyboardButton(text=f"{n} ({q})", callback_data=f"d_{quote(n)}")] for n, q, _ in first]
    kb.extend([
        [InlineKeyboardButton("🔄", callback_data="r")],
        [InlineKeyboardButton("📉", callback_data="l")],
        [InlineKeyboardButton("➕", callback_data="a")]
    ])
    
    await bot.send_message(
        chat_id=user_id, 
        text=text, 
        parse_mode="Markdown", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)  # ✅ ИСПРАВЛЕНО!
    )

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
                        await check_notifications()
                    break
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"Цикл ошибка: {e}")

async def check_notifications():
    try:
        products = await database.get_all_products()
        low = [(n, q, u) for n, q, u in products if float(q) <= 1]
        if not low: return
        
        text = f"⚠️ *НАПОМИНАНИЕ* ⚠️\n\n📉 *Осталось мало:* \n" + "\n".join(f"• `{n}`: {q} {u}" for n, q, u in low)
        text += "\n🛒 Пора купить!"
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        logging.info("Уведомление отправлено")
    except Exception as e:
        logging.error(f"Уведомление ошибка: {e}")

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
