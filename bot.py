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

# --- МАШИНА СОСТОЯНИЙ ---
class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

CHUNK_SIZE = 20
last_notification_check_day = None

# Функция для создания главного меню (убрали зависимости от keyboards.py)
def create_main_menu():
    kb = [
        [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# === ГЛАВНОЕ МЕНЮ ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я ваш Умный Холодильник 🧊\n\n"
        "Что хотите сделать?",
        reply_markup=create_main_menu()
    )

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        kb = [[InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_product")]]
        await message.answer("❌ Холодильник пуст! Добавьте что-нибудь.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    
    for chunk in chunks:
        await send_list_chunk(message, chunk)
    if len(chunks) > 1:
        await asyncio.sleep(1)

async def send_list_chunk(message, products):
    text = f"📋 **Список продуктов:**\n\n"
    for name, qty, unit in products:
        icon = "⚠️" if float(qty) <= 1 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    keyboard = []
    for name, qty, unit in products:
        encoded_name = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"d_{encoded_name}_d"),
            InlineKeyboardButton(text=f"{name}", callback_data="i"),
            InlineKeyboardButton(text="➕", callback_data=f"d_{encoded_name}_a"),
            InlineKeyboardButton(text="🗑", callback_data=f"d_{encoded_name}_x")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="low_qty")])
    keyboard.append([InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_product")])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

# === ДОБАВЛЕНИЕ ПРОДУКТА --- ПОШАГОВО ===
@dp.callback_query(F.data == "add_product")
async def start_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.edit_text("Напишите название продукта (например: Молоко):")
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    if not message.text.strip():
        # Исправлено: создаём клавиатуру напрямую без импорта
        main_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]], 
            resize_keyboard=True
        )
        await message.answer("⚠️ Введите название продукта:", reply_markup=main_kb)
        return
        
    await state.update_data(name=message.text.strip())
    # Исправлено: тоже здесь
    main_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]], 
        resize_keyboard=True
    )
    await message.answer("Теперь напишите количество (числом, можно с запятой):", reply_markup=main_kb)
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        float(message.text.replace(',', '.'))
        await state.update_data(quantity=float(message.text.replace(',', '.')))
        
        units_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука/шт.", callback_data="u_piece")],
            [InlineKeyboardButton(text="🥛 Пол-литра/бут.", callback_data="u_half")],
            [InlineKeyboardButton(text="🧱 Пачка/пакет", callback_data="u_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка/л", callback_data="u_bottle")],
            [InlineKeyboardButton(text="🥗 Тарелка/блюдо", callback_data="u_plate")]
        ])
        
        await message.answer("Выберите единицу измерения:", reply_markup=units_kb)
        await state.set_state(AddProduct.unit)
        
    except ValueError:
        main_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]], 
            resize_keyboard=True
        )
        await message.answer("❌ Пожалуйста, введите корректное число!", reply_markup=main_kb)

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    unit_map = {"piece": "штука", "half": "пол-литра", "pack": "пачка", "bottle": "бутылка", "plate": "блюдо"}
    unit = unit_map[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await callback.message.edit_text(f"✅ **Готово!** `{name}`: {qty} {unit}")
    await state.clear()

# === ОБРАБОТКА ВСЕХ КНОПОК ОДНЫМ БЛОКОМ ===
@dp.callback_query(F.data.startswith(("d_", "r", "l", "s")))
async def handle_all_buttons(callback: types.CallbackQuery):
    try:
        data = callback.data
        
        # Изменить количество / удалить
        if data.startswith("d_"):
            parts = data.split("_")
            action = parts[2][0]  # d/a/x
            name = unquote(parts[1])
            
            if action == "d":  # минус
                new_qty = await database.change_quantity(name, -1)
                await callback.answer(f"✓ {name}: {new_qty}")
            elif action == "a":  # плюс
                new_qty = await database.change_quantity(name, 1)
                await callback.answer(f"✓ {name}: {new_qty}")
            elif action == "x":  # удалить
                await database.delete_product(name)
                await callback.answer(f"✓ {name} удален")
                
            await refresh_last_message(callback.from_user.id)
            
        elif data == "r":  # обновить
            await callback.answer("Обновляю...", show_alert=False)
            await refresh_last_message(callback.from_user.id)
            
        elif data == "l":  # мало продуктов
            await callback.answer("Показываю продукты с низким запасом...")
            await show_low_quantity_list(callback.from_user.id)
            
    except Exception as e:
        logging.error(f"Ошибка кнопки: {e}")
        await callback.answer("❌ Ошибка при обработке", show_alert=True)

async def show_low_quantity_list(user_id):
    products = await database.get_all_products()
    low_products = [(name, qty, unit) for name, qty, unit in products if float(qty) <= 1]
    
    if not low_products:
        kb = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh")]]
        await bot.send_message(chat_id=user_id, text="✅ Все продукты в нормальном количестве!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    text = "📉 **Продуктов осталось мало:**\n\n"
    for name, qty, unit in low_products:
        icon = "⚠️" if float(qty) < 0.5 else "💡"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    keyboard = []
    for name, qty, unit in low_products:
        encoded_name = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"d_{encoded_name}_d"),
            InlineKeyboardButton(text=f"{name}", callback_data="i"),
            InlineKeyboardButton(text="➕", callback_data=f"d_{encoded_name}_a"),
            InlineKeyboardButton(text="🗑", callback_data=f"d_{encoded_name}_x")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh")])
    keyboard.append([InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_product")])
    
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

async def refresh_last_message(user_id):
    try:
        await asyncio.sleep(0.05)
        products = await database.get_all_products()
        
        if not products:
            return
        
        first_chunk = products[:CHUNK_SIZE]
        text = f"📋 **Актуальный список:**\n\n"
        for name, qty, unit in first_chunk:
            icon = "⚠️" if float(qty) <= 1 else "✅"
            text += f"{icon} `{name}`: {qty} {unit}\n"
        
        if len(products) > CHUNK_SIZE:
            text += f"\n💡 Всего: {len(products)} продуктов"
        
        keyboard = []
        for name, qty, unit in first_chunk:
            encoded_name = quote(name)
            row = [
                InlineKeyboardButton(text="➖", callback_data=f"d_{encoded_name}_d"),
                InlineKeyboardButton(text=f"{name}", callback_data="i"),
                InlineKeyboardButton(text="➕", callback_data=f"d_{encoded_name}_a"),
                InlineKeyboardButton(text="🗑", callback_data=f"d_{encoded_name}_x")
            ]
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh")])
        keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="l")])
        keyboard.append([InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_product")])
        
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        print(f"Ошибка обновления: {e}")

# === УВЕДОМЛЕНИЯ ===
async def notification_worker():
    global last_notification_check_day
    hours = [11, 16, 16]  
    minutes = ["00", "00", "30"]  
    
    while True:
        try:
            now = datetime.now()
            for idx, check_hour in enumerate(hours):
                target_min = minutes[idx]
                if now.hour == check_hour and now.minute >= int(target_min):
                    if now.day != last_notification_check_day:
                        last_notification_check_day = now.day
                        try:
                            await check_low_quantity_notifications()
                        except Exception as e:
                            logging.error(f"Ошибка уведомления: {e}")
                    break
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"Ошибка цикла уведомлений: {e}")

async def check_low_quantity_notifications():
    try:
        products = await database.get_all_products()
        low_products = [(name, qty, unit) for name, qty, unit in products if float(qty) <= 1]
        
        if not low_products:
            return
        
        now = datetime.now().strftime("%H:%M")
        text = f"⚠️ *НАПОМИНАНИЕ* ⚠️\n\n⏰ Время: {now}\n\n📉 *Осталось мало:* \n"
        
        for name, qty, unit in low_products:
            text += f"• `{name}`: {qty} {unit}\n"
        
        text += "\n🛒 Пора купить!"
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        logging.info(f"Уведомление отправлено")
    except Exception as e:
        logging.error(f"Ошибка уведомления: {e}")

# === ЗАПУСК ===
async def main():
    try:
        await database.init_db()
        print("База данных готова")
    except Exception as e:
        print(f"Ошибка базы данных: {e}")
    
    print("🤖 Бот запущен...")
    asyncio.create_task(notification_worker())
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
