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

CHUNK_SIZE = 50

def get_safe_name(name):
    return re.sub(r'[^a-z0-9]', '_', str(name).lower())[:30]

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]
    ], resize_keyboard=True)

async def create_product_kb(products):
    """Создает кнопки для всех продуктов"""
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
        [InlineKeyboardButton(text="📉 Показать мало (<3)", callback_data="low_q")],
        [InlineKeyboardButton(text="➕ Добавить новый продукт", callback_data="add_new")]
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def send_products_list(message, products):
    """Отправляет список продуктов с кнопками"""
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_new")]])
        await message.answer("❌ Холодильник пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    text = f"📋 **Список ({len(products)}):**\n\n"
    chunk = products[:CHUNK_SIZE]
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = await create_product_kb(products)
    msg = await message.answer(text, parse_mode="Markdown", reply_markup=markup)
    
    # Сохраняем ID сообщения для пользователя
    user_last_messages = {}
    user_last_messages[message.from_user.id] = {'message_id': msg.message_id, 'chat_id': message.chat.id}
    return msg

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    await send_products_list(message, products)

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
        await message.answer("Выберите единицу измерения:", reply_markup=units_kb)
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
    # Показываем обновленный список
    await refresh_list_from_user(callback.from_user.id)

@dp.callback_query(F.data.startswith("dec_") or F.data.startswith("inc_") or F.data.startswith("del_"))
async def change_quantity(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        action = parts[0]  # dec / inc / del
        safe_name = "_".join(parts[1:]) if len(parts) > 1 else ""
        
        if action == "del":
            await database.delete_product(safe_name)
            await callback.answer(f"✓ {safe_name} удален", show_alert=False)
        elif action == "dec":
            new_qty = await database.change_quantity(safe_name, -1)
            await callback.answer(f"✓ {new_qty}", show_alert=False)
        elif action == "inc":
            new_qty = await database.change_quantity(safe_name, 1)
            await callback.answer(f"✓ {new_qty}", show_alert=False)
        
        # Отправляем новый список вместо редактирования
        await refresh_list_from_user(callback.from_user.id)
        
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "info")
async def any_info(callback: types.CallbackQuery):
    await callback.answer("Информация о продукте", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_list_from_user(callback.from_user.id)

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

async def refresh_list_from_user(user_id):
    """Отправляет новый список продуктов вместо редактирования старого"""
    products = await database.get_all_products()
    
    # Для текущего чата создадим фейковый объект для show_list
    class FakeChat:
        id = user_id
    
    class FakeUser:
        id = user_id
    
    # Создаем минимальный объект сообщения
    from aiogram.types import Message, Chat, User
    
    chat = Chat(id=user_id, type="private")
    user = User(id=user_id, first_name="User", is_bot=False)
    
    fake_msg = Message(message_id=999999, date=datetime.now(), chat=chat, from_user=user)
    
    # Отправляем новое сообщение через send_products_list
    await send_products_list(fake_msg, products)

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
