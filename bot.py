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
import keyboards

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

MAX_PRODUCTS = 50

# === ГЛАВНОЕ МЕНЮ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=keyboards.get_main_menu())

# === СПИСОК ПРОДУКТОВ ===
@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_new")]])
        await message.answer("❌ Пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    text = f"📋 **Список ({len(products)}):**\n\n"
    chunk = products[:MAX_PRODUCTS]
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = keyboards.get_product_keyboard(products)
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

# === ДОБАВЛЕНИЕ ПРОДУКТА ===
@dp.callback_query(F.data == "add_new")
async def add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.reply("Название продукта:", reply_markup=keyboards.get_main_menu())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    main_kb = keyboards.get_main_menu()
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
        await message.answer("❌ Неправильное число!", reply_markup=keyboards.get_main_menu())

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
    await refresh_list(callback.from_user.id, callback.message.chat.id)

# === ОБРАБОТКА КНОПОК ===
@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, -1)
        await callback.answer(f"✓ {new_qty}", show_alert=False)
        await refresh_list(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("inc_"))
async def increase_qty(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, 1)
        await callback.answer(f"✓ {new_qty}", show_alert=False)
        await refresh_list(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        await database.delete_product(name)
        await callback.answer(f"✓ Удален", show_alert=False)
        await refresh_list(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "info")
async def any_info(callback: types.CallbackQuery):
    await callback.answer("Информация о продукте", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_list(callback.from_user.id, callback.message.chat.id)

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

async def refresh_list(user_id, chat_id):
    """Отправляет обновлённый список продуктов"""
    products = await database.get_all_products()
    
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_new")]])
        await bot.send_message(chat_id=chat_id, text="❌ Пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    text = f"📋 **Актуальный список ({len(products)}):**\n\n"
    chunk = products[:MAX_PRODUCTS]
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = keyboards.get_product_keyboard(products)
    await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=markup)

# === УВЕДОМЛЕНИЯ ===
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
    try:
        await database.init_db()
        print("База готова")
    except Exception as e:
        print(f"Ошибка базы: {e}")
    print("🤖 Запущен!")
    asyncio.create_task(start_health_server())
    asyncio.create_task(notification_worker())
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Выключен")
