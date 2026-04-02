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

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]
    ], resize_keyboard=True)

def get_product_keyboard(products):
    kb = []
    for name, qty, unit in products:
        safe_name = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{safe_name}"),
            InlineKeyboardButton(text=name, callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"d_a_{safe_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"d_x_{safe_name}")
        ]
        kb.append(row)
    
    kb.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")],
        [InlineKeyboardButton(text="📉 Мало (≤3)", callback_data="low_q")],
        [InlineKeyboardButton(text="➕ Новый продукт", callback_data="add_new")]
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def list_cmd(message: types.Message):
    await show_list(message)

async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="a")]])
        await message.answer("❌ Пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    text = f"📋 **Список ({len(products)}):**\n\n"
    for name, qty, unit in products[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = get_product_keyboard(products)
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.callback_query(F.data == "a")
async def add_from_list(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.reply("Напишите название продукта:", reply_markup=keyboards.get_main_menu())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Введите количество (числом):", reply_markup=get_main_kb())
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
        await message.answer("❌ Число!", reply_markup=get_main_kb())

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "lit": "литр", "pack": "пачка", "bot": "бутылка", "plt": "блюдо"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await callback.message.delete()
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ `{name}`: {qty} {unit}", parse_mode="Markdown")
    await state.clear()
    await show_list(callback.message)

@dp.callback_query(F.data.startswith("d_"))
async def change_qty(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_", 1)
        action = parts[0]
        name = unquote(parts[1])
        
        if action == "inc":
            new_qty = await database.change_quantity(name, 1)
            await callback.answer(f"➕ {name}: {new_qty}", show_alert=False)
        elif action == "del":
            await database.delete_product(name)
            await callback.answer(f"🗑 {name} удалён", show_alert=False)
        
        await refresh_list(callback.message)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "lit": "литр", "pack": "пачка", "bot": "бутылка", "plt": "блюдо"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await callback.message.delete()
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ `{name}`: {qty} {unit}", parse_mode="Markdown")
    await state.clear()
    await show_list(callback.message)

@dp.callback_query(F.data.startswith("dec_"))
async def dec_qty(callback: types.CallbackQuery):
    try:
        safe_name = callback.data.split("_")[1]
        new_qty = await database.change_quantity(name, -1)
        await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
        await refresh_last(callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        await database.delete_product(name)
        await callback.answer(f"🗑 {name} удалён", show_alert=False)
        await refresh_last(callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low_q")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

@dp.callback_query(F.data == "refresh")
async def refresh(callback......

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
