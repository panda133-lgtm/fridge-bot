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

def get_safe_name(name):
    return re.sub(r'[^a-z0-9]', '_', str(name).lower())[:30]

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]
    ], resize_keyboard=True)

async def get_product_keyboard(products):
    kb = []
    for name, qty, unit in products:
        safe_name = get_safe_name(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{safe_name}"),
            InlineKeyboardButton(text=name, callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{safe_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{safe_name}")
        ]
        kb.append(row)
    
    kb.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")],
        [InlineKeyboardButton(text="📉 Мало (<3)", callback_data="low_q")],
        [InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_new")]
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_new")]])
        await message.answer("❌ Пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    text = f"📋 **Список ({len(products)}):**\n\n"
    chunk = products[:50]
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = await get_product_keyboard(products)
    msg = await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.callback_query(F.data == "add_new")
async def add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.reply("Название продукта:", reply_markup=get_main_kb())
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
            [InlineKeyboardButton(text="🍏 Штука/шт", callback_data="u_pie")],
            [InlineKeyboardButton(text="🥛 Литр/л", callback_data="u_lit")],
            [InlineKeyboardButton(text="🧱 Пачка/шт", callback_data="u_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка/шт", callback_data="u_bot")],
            [InlineKeyboardButton(text="🥗 Тарелка/блюдо", callback_data="u_plt")]
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
    await show_list_with_buttons(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        safe_name = "_".join(parts[1:])
        new_qty = await database.change_quantity(safe_name, -1)
        await callback.answer(f"✓ {new_qty}", show_alert=False)
        await show_list_with_buttons(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("inc_"))
async def increase_qty(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        safe_name = "_".join(parts[1:])
        new_qty = await database.change_quantity(safe_name, 1)
        await callback.answer(f"✓ {new_qty}", show_alert=False)
        await show_list_with_buttons(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        safe_name = "_".join(parts[1:])
        await database.delete_product(safe_name)
        await callback.answer(f"✓ Удален", show_alert=False)
        await show_list_with_buttons(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "info")
async def any_info(callback: types.CallbackQuery):
    await callback.answer("Информация о продукте", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await show_list_with_buttons(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    products = await database.get_all_products()
    low = [(n, q, u) for n, q, u in products if float(q) <= 3]
    
    if not low:
        await bot.send_message(chat_id=callback.from_user.id, text="✅ Всё ок (>3)")
        return
    
    text = "📉 **Мало осталось (≤3):**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n, q, u in low)
    kb = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh")]]
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await bot.send_message(chat_id=callback.from_user.id, text=text, parse_mode="Markdown", reply_markup=markup)

async def show_list_with_buttons(user_id, chat_id):
    """Отправляет список продуктов используя bot.send_message"""
    products = await database.get_all_products()
    
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_new")]])
        await bot.send_message(chat_id=chat_id, text="❌ Пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    text = f"📋 **Актуальный список ({len(products)}):**\n\n"
    chunk = products[:50]
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = await get_product_keyboard(products)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=markup)

async def notification_worker():
    global last_notification_day
    hours = [11, 16, 16]  
    minutes = ["00", "00", "30"]  
    last_notification_day = None
    
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
