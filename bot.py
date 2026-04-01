import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
from aiohttp import web
from urllib.parse import quote, unquote

import database
import keyboards

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env!")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

CHUNK_SIZE = 20
last_notification_check_day = None

# === ГЛАВНАЯ КОМАНДА ===
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я ваш Умный Холодильник 🧊\n"
        "Я помогу не забыть купить еду.\n"
        "Используйте кнопки внизу или пишите мне.",
        reply_markup=keyboards.get_main_menu()
    )

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        text = f"❌ Холодильник пуст! Добавьте что-нибудь."
        await message.answer(text)
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    
    for i, chunk in enumerate(chunks[:5]):
        await send_list_chunk(message, chunk, current=i+1, total=len(chunks))
    
    if len(chunks) > 5:
        await asyncio.sleep(1.5)
        for chunk in chunks[5:]:
            await send_list_chunk(message, chunk)

async def send_list_chunk(message, products, current=None, total=None):
    status_prefix = ""
    if current and total:
        status_prefix = f"[{current}/{total}] "
    
    text = f"📋 **Список продуктов {status_prefix}**:\n\n"
    for name, qty, unit in products:
        icon = "⚠️" if float(qty) <= 1 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    # Кнопки для каждого продукта
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
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="r")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="l")])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

# === ДОБАВЛЕНИЕ ПРОДУКТА ===
@dp.message(Command("add"))
@dp.message(F.text == "➕ Добавить вручную")
async def start_add_process(message: types.Message, state: FSMContext):
    await message.answer("Напиши название продукта (например: Молоко):")
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Теперь напиши количество (числом, можно с запятой):")
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    try:
        float(message.text.replace(',', '.'))
        await state.update_data(quantity=float(message.text.replace(',', '.')))
        
        units_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука/шт.", callback_data="u_pie")],
            [InlineKeyboardButton(text="🥛 Пол-литра/шт.", callback_data="u_hal")],
            [InlineKeyboardButton(text="🧱 Пачка/пакет", callback_data="upac")],
            [InlineKeyboardButton(text="🍶 Бутылка/л", callback_data="u_bott")],
            [InlineKeyboardButton(text="🥗 Тарелка/блюдо", callback_data="u_plat")]
        ])
        
        await message.answer("Выберите единицу измерения:", reply_markup=units_kb)
        await state.set_state(AddProduct.unit)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число!")

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    unit_map = {"pie": "штука", "hal": "пол-литра", "upac": "пачка", "u_bott": "бутылка", "u_plat": "блюдо"}
    unit = unit_map[callback.data]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ Готово! `{name}`: {qty} {unit}")
    await state.clear()

# === ОБРАБОТКА ВСЕХ КНОПОК ОДНЫМ ОБРАБОТЧИКОМ ===
@dp.callback_query(F.data.startswith(("d_", "r", "l", "i")))
async def handle_all_buttons(callback: types.CallbackQuery):
    """ОБЩИЙ ОБРАБОТЧИК ДЛЯ ВСЕХ ИНСТРУМЕНТОВ"""
    try:
        data = callback.data
        
        if data == "r":  # Обновить список
            await callback.answer("Обновляю...", show_alert=False)
            await refresh_last_message(callback.from_user.id)
            
        elif data == "l":  # Показать мало продуктов
            await callback.answer("Показываю продукты с низким запасом...", show_alert=False)
            await show_low_quantity_list(callback.from_user.id)
            
        elif data == "i":  # Инфо (ничего не делаем)
            await callback.answer("Ничего не делать", show_alert=True)
            
        elif data.startswith("d_"):  # Изменить количество
            parts = data.split("_")
            if len(parts) == 3:  # d_название_действие
                action = parts[2]
                name = unquote(parts[1])
                
                if action == "d":  # минус
                    new_qty = await database.change_quantity(name, -1)
                    await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
                    
                elif action == "a":  # плюс
                    new_qty = await database.change_quantity(name, 1)
                    await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
                    
                elif action == "x":  # удалить
                    await database.delete_product(name)
                    await callback.answer(f"✓ {name} удален", show_alert=False)
                
                await refresh_last_message(callback.from_user.id)
                
    except Exception as e:
        logging.error(f"Ошибка кнопки: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

async def show_low_quantity_list(user_id):
    products = await database.get_all_products()
    low_products = [(name, qty, unit) for name, qty, unit in products if float(qty) <= 1]
    
    if not low_products:
        text = "✅ Все продукты в нормальном количестве!"
        kb = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="r")]]
        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        return
    
    text = "📉 **Продуктов осталось мало:**\n\n"
    for name, qty, unit in low_products:
        icon = "⚠️" if float(qty) < 0.5 else "💡"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    text += "\n💡 Добавьте новые!"
    
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
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data="r")])
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

async def refresh_last_message(user_id):
    try:
        await asyncio.sleep(0.1)
        products = await database.get_all_products()
        
        if not products:
            return
        
        chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
        first_chunk = chunks[0]
        
        text = f"📋 **Актуальный список:**\n\n"
        for name, qty, unit in first_chunk:
            icon = "⚠️" if float(qty) <= 1 else "✅"
            text += f"{icon} `{name}`: {qty} {unit}\n"
        
        if len(products) > CHUNK_SIZE:
            text += f"\n💡 Всего: {len(products)} продуктов (показаны первые 20)"
        
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
        
        keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="r")])
        keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="l")])
        
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
    except Exception as e:
        print(f"Ошибка при обновлении: {e}")

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
        text = f"⚠️ *НАПОМИНАНИЕ О ПРОДУКТАХ* ⚠️\n\n⏰ Время: {now}\n\n📉 *Осталось мало:* \n"
        
        for name, qty, unit in low_products:
            text += f"• `{name}`: {qty} {unit}\n"
        
        text += "\n🛒 Порекомендуем купить эти продукты!"
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        logging.info(f"Уведомление отправлено на {now}")
    except Exception as e:
        logging.error(f"Ошибка проверки уведомлений: {e}")

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
