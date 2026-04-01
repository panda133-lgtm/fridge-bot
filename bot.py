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
import re

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

# Создаем безопасный идентификатор для продукта
def get_safe_id(name):
    return re.sub(r'[^a-z0-9]', '_', name.lower())[:30]

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]
    ], resize_keyboard=True)

async def send_list(message, products, start_idx=0, end_idx=None):
    if end_idx is None:
        end_idx = min(start_idx + CHUNK_SIZE, len(products))
    
    text = f"📋 **Список ({start_idx+1}-{end_idx} из {len(products)}):**\n\n"
    chunk = products[start_idx:end_idx]
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    # Кнопки для каждого продукта в строке
    kb = []
    for name, qty, unit in chunk:
        safe_id = get_safe_id(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"d_{safe_id}_dec"),
            InlineKeyboardButton(text=name, callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"d_{safe_id}_inc"),
            InlineKeyboardButton(text="🗑", callback_data=f"d_{safe_id}_del")
        ]
        kb.append(row)
    
    # Общие кнопки внизу
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")])
    kb.append([InlineKeyboardButton(text="📉 Мало (<3)", callback_data="low")])
    kb.append([InlineKeyboardButton(text="➕ Новый продукт", callback_data="add_new")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_new")]])
        await message.answer("❌ Холодильник пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    for i, chunk in enumerate(chunks):
        await send_list(message, products, start_idx=i*CHUNK_SIZE, end_idx=min((i+1)*CHUNK_SIZE, len(products)))

@dp.callback_query(F.data == "add_new")
async def add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    msg = await callback.message.reply("Название продукта:", reply_markup=get_main_kb())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    main_kb = get_main_kb()
    if not message.text.strip():
        await message.answer("⚠️ Введите название!", reply_markup=main_kb)
        return
    await state.update_data(name=message.text.strip())
    await message.answer("Количество (числом):", reply_markup=main_kb)
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(quantity=val)
        
        units_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука", callback_data="u_pie")],
            [InlineKeyboardButton(text="🥛 Литр", callback_data="u_lit")],
            [InlineKeyboardButton(text="🧱 Пачка", callback_data="u_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка", callback_data="u_bot")],
            [InlineKeyboardButton(text="🥗 Блюдо", callback_data="u_plt")]
        ])
        await message.answer("Выберите единицу:", reply_markup=units_kb)
        await state.set_state(AddProduct.unit)
    except ValueError:
        await message.answer("❌ Неправильное число!", reply_markup=get_main_kb())

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "lit": "литр", "pack": "пачка", "bot": "бутылка", "plt": "блюдо"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await callback.message.delete()
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ Готово! `{name}`: {qty} {unit}", parse_mode="Markdown")
    await state.clear()

@dp.callback_query(F.data.startswith("d_"))
async def handle_buttons(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        safe_id = "_".join(parts[1:-1])
        action = parts[-1]
        
        if action == "dec":
            new_qty = await database.change_quantity(safe_id, -1)
            await callback.answer(f"✓ Уменьшил", show_alert=False)
        elif action == "inc":
            new_qty = await database.change_quantity(safe_id, 1)
            await callback.answer(f"✓ Увеличил", show_alert=False)
        elif action == "del":
            await database.delete_product(safe_id)
            await callback.answer(f"✓ Удалил", show_alert=False)
        
        await refresh_last(callback.from_user.id)
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "info")
async def any_info(callback: types.CallbackQuery):
    await callback.answer("Информация", show_alert=True)

async def show_low(user_id):
    products = await database.get_all_products()
    low = [(n, q, u) for n, q, u in products if float(q) <= 3]
    
    if not low:
        await bot.send_message(chat_id=user_id, text="✅ Всё ок! (<3)")
        return
    
    text = "📉 **Мало осталось (≤3):**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n, q, _ in low)
    kb = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh")]]
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=markup)

async def refresh_last(user_id):
    products = await database.get_all_products()
    if not products: 
        await bot.send_message(chat_id=user_id, text="❌ Пуст!")
        return
    
    first = products[:CHUNK_SIZE]
    text = f"📋 **Актуальный список:**\n\n" + "\n".join(f"{'⚠️' if float(q)<=3 else '✅'} `{n}`: {q} {u}" for n, q, u in first)
    
    kb = [[InlineKeyboardButton(text=f"{n}", callback_data=f"d_{get_safe_id(n)}_inc")] for n, q, _ in first]
    kb.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")],
        [InlineKeyboardButton(text="📉 Показать мало", callback_data="low")],
        [InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_new")]
    ])
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=markup)

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
        low = [(n, q, u) for n, q, u in products if float(q) <= 3]
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
