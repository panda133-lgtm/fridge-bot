import asyncio, logging, os, re
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from aiohttp import web
from urllib.parse import quote, unquote

import database, keyboards

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

# === ГЛАВНОЕ МЕНЮ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=keyboards.get_main_menu())

# === СПИСОК ===
@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    if not products:
        await message.answer("❌ Пуст!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add")]]))
        return
    text = f"📋 **Список ({len(products)}):**\n\n"
    for name, qty, unit in products[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboards.get_product_keyboard(products))

# === ДОБАВЛЕНИЕ ===
@dp.callback_query(F.data == "add")
async def add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.reply("Название:", reply_markup=keyboards.get_main_menu())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    if not message.text.strip():
        await message.answer("⚠️ Введите название!", reply_markup=keyboards.get_main_menu())
        return
    await state.update_data(name=message.text.strip())
    await message.answer("Количество:", reply_markup=keyboards.get_main_menu())
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        val = float(message.text.replace(',', '.'))
        await state.update_data(quantity=val)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука", callback_data="u_pie")],
            [InlineKeyboardButton(text="🥛 Литр", callback_data="u_lit")],
            [InlineKeyboardButton(text="🧱 Пачка", callback_data="u_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка", callback_data="u_bot")],
            [InlineKeyboardButton(text="🥗 Блюдо", callback_data="u_plt")]
        ])
        await message.answer("Единица:", reply_markup=kb)
        await state.set_state(AddProduct.unit)
    except:
        await message.answer("❌ Число!", reply_markup=keyboards.get_main_menu())

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "lit": "литр", "pack": "пачка", "bot": "бутылка", "plt": "блюдо"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    await database.add_or_update_product(data['name'], str(data['quantity']), unit)
    await callback.message.delete()
    await bot.send_message(callback.from_user.id, f"✅ Готово! {data['name']}: {data['quantity']} {unit}")
    await state.clear()
    await refresh(callback.from_user.id, callback.message.chat.id)

# === КНОПКИ СПИСКА ===
@dp.callback_query(F.data.startswith("dec_"))
async def dec(callback: types.CallbackQuery):
    name = unquote(callback.data.split("_",1)[1])
    await database.change_quantity(name, -1)
    await callback.answer("✓", show_alert=False)
    await refresh(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data.startswith("inc_"))
async def inc(callback: types.CallbackQuery):
    name = unquote(callback.data.split("_",1)[1])
    await database.change_quantity(name, 1)
    await callback.answer("✓", show_alert=False)
    await refresh(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data.startswith("del_"))
async def delete(callback: types.CallbackQuery):
    name = unquote(callback.data.split("_",1)[1])
    await database.delete_product(name)
    await callback.answer("✓", show_alert=False)
    await refresh(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data == "info")
async def info(callback: types.CallbackQuery):
    await callback.answer("ℹ️", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh_btn(callback: types.CallbackQuery):
    await callback.answer("🔄", show_alert=False)
    await refresh(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data == "low")
async def low(callback: types.CallbackQuery):
    products = await database.get_all_products()
    low = [(n,q,u) for n,q,u in products if float(q) <= 3]
    if not low:
        await bot.send_message(callback.from_user.id, "✅ Всё ок")
        return
    text = "📉 **Мало:**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n,q,u in low)
    await bot.send_message(callback.from_user.id, text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙", callback_data="refresh")]]))

async def refresh(user_id, chat_id):
    products = await database.get_all_products()
    if not products:
        await bot.send_message(chat_id, "❌ Пуст", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕", callback_data="add")]]))
        return
    text = f"📋 **Список:**\n\n" + "\n".join(f"{'⚠️' if float(q)<=3 else '✅'} `{n}`: {q} {u}" for n,q,u in products[:50])
    await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=keyboards.get_product_keyboard(products))

# === ЗАПУСК ===
async def main():
    await database.init_db()
    print("🤖 Запущен!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
