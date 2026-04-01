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
last_notification_day = None

# Храним последнее сообщение от каждого пользователя для обновления
user_last_messages = {}

def get_safe_name(name):
    return re.sub(r'[^a-z0-9]', '_', str(name).lower())[:30]

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]
    ], resize_keyboard=True)

async def create_product_rows(products, start_idx=0, end_idx=None):
    """Создает строки с кнопками для продуктов"""
    if end_idx is None:
        end_idx = min(start_idx + CHUNK_SIZE, len(products))
    
    chunk = products[start_idx:end_idx]
    kb = []
    
    for name, qty, unit in chunk:
        safe_name = get_safe_name(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"d_{safe_name}_dec"),
            InlineKeyboardButton(text=name, callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"d_{safe_name}_inc"),
            InlineKeyboardButton(text="🗑", callback_data=f"d_{safe_name}_del")
        ]
        kb.append(row)
    
    # Общие кнопки
    kb.extend([
        [InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh")],
        [InlineKeyboardButton(text="📉 Мало (<3)", callback_data="low")],
        [InlineKeyboardButton(text="➕ Новый продукт", callback_data="add_new")]
    ])
    
    return kb

async def send_product_list(message, products, is_update=False):
    """Отправляет или обновляет список продуктов"""
    start_idx = 0
    end_idx = min(CHUNK_SIZE, len(products))
    chunk = products[start_idx:end_idx]
    
    text = f"📋 **Актуальный список ({len(products)}):**\n\n"
    
    for name, qty, unit in chunk:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    kb = await create_product_rows(products, start_idx, end_idx)
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    if is_update and message.id == user_last_messages.get(message.from_user.id, {}).get('message_id'):
        # Обновляем старое сообщение
        await bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=message.id,
            text=text,
            parse_mode="Markdown",
            reply_markup=markup
        )
    else:
        # Отправляем новое сообщение
        msg = await message.answer(text, parse_mode="Markdown", reply_markup=markup)
        
        # Сохраняем ID для будущего обновления
        user_last_messages[message.from_user.id] = {
            'message_id': msg.id,
            'chat_id': message.chat.id,
            'products': products
        }
        
        return msg

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Умный Холодильник 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_new")]])
        await message.answer("❌ Холодильник пуст!\n\nНажми ➕ чтобы добавить.", reply_markup=markup)
        return
    
    await send_product_list(message, products)

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
    # Обновить после добавления
    await refresh_list_from_callback(callback.from_user.id, callback.from_user.id)

@dp.callback_query(F.data.startswith("d_"))
async def handle_action(callback: types.CallbackQuery):
    try:
        parts = callback.data.split("_")
        safe_name = "_".join(parts[1:-1])
        action = parts[-1]
        
        if action == "dec":
            new_qty = await database.change_quantity(safe_name, -1)
            await callback.answer(f"✓ Уменьшил", show_alert=False)
        elif action == "inc":
            new_qty = await database.change_quantity(safe_name, 1)
            await callback.answer(f"✓ Увеличил", show_alert=False)
        elif action == "del":
            await database.delete_product(safe_name)
            await callback.answer(f"✓ Удалил", show_alert=False)
        
        await refresh_last(callback.from_user.id)
    except Exception as e:
        logging.error(f"Ошибка кнопки: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "info")
async def any_info(callback: types.CallbackQuery):
    await callback.answer("Информация о продукте", show_alert=True)

@dp.callback_query(F.data == "refresh")
async def refresh(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last(callback.from_user.id)

@dp.callback_query(F.data == "low")
async def low_q(callback: types.CallbackQuery):
    await callback.answer("Показываю мало...", show_alert=False)
    await show_low(callback.from_user.id)

async def refresh_last(user_id):
    await refresh_list_from_callback(user_id, user_id)

async def refresh_list_from_callback(user_id, source_chat):
    try:
        msg_data = user_last_messages.get(source_chat)
        
        if not msg_data:
            await bot.send_message(chat_id=user_id, text="❌ Найдено свежих данных")
            return
        
        msg_id = msg_data['message_id']
        chat_id = msg_data['chat_id']
        products = await database.get_all_products()
        
        if not products:
            await bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="❌ Холодильник пуст!")
            return
        
        start_idx = 0
        end_idx = min(CHUNK_SIZE, len(products))
        chunk = products[start_idx:end_idx]
        
        text = f"📋 **Актуальный список ({len(products)}):**\n\n"
        for name, qty, unit in chunk:
            icon = "⚠️" if float(qty) <= 3 else "✅"
            text += f"{icon} `{name}`: {qty} {unit}\n"
        
        kb = await create_product_rows(products, start_idx, end_idx)
        markup = InlineKeyboardMarkup(inline_keyboard=kb)
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=markup
        )
        
        # Обновить сохраненные данные
        user_last_messages[source_chat] = {'message_id': msg_id, 'chat_id': chat_id, 'products': products}
        
    except Exception as e:
        logging.error(f"Ошибка обновления: {e}")

async def show_low(user_id):
    products = await database.get_all_products()
    low = [(n, q, u) for n, q, u in products if float(q) <= 3]
    
    if not low:
        await bot.send_message(chat_id=user_id, text="✅ Всё ок! (>3)")
        return
    
    text = "📉 **Мало осталось (≤3):**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n, q, u in low)
    kb = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh")]]
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
