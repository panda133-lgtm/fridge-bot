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
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить вручную")]
    ], resize_keyboard=True)
    await message.answer(
        "Привет! Я ваш Умный Холодильник 🧊\n"
        "Я помогу не забыть купить еду.\n\n"
        "Выберите действие снизу:",
        reply_markup=kb
    )

# === СПИСОК ПРОДУКТОВ ===
@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        text = f"❌ Холодильник пуст! Добавьте что-нибудь."
        kb = [[InlineKeyboardButton(text="➡️ Добавить продукт", callback_data="add_product")]]
        await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
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
    
    keyboard = []
    for name, qty, unit in products:
        encoded_name = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
            InlineKeyboardButton(text=f"{name} ({qty})", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="low_qty")])
    keyboard.append([InlineKeyboardButton(text="➡️ Добавить новый", callback_data="add_product")])
    
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
        
        # ВЫБОР ЕДИНИЦ ИЗМЕРЕНИЯ (отдельный блок для избежания конфликтов)
        units_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука/шт.", callback_data="select_unit_piece")],
            [InlineKeyboardButton(text="🥛 Пол-литра/бут.", callback_data="select_unit_half")],
            [InlineKeyboardButton(text="🧱 Пачка/пакет", callback_data="select_unit_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка/л", callback_data="select_unit_bottle")],
            [InlineKeyboardButton(text="🥗 Тарелка/блюдо", callback_data="select_unit_plate")]
        ])
        
        await message.answer("Выберите единицу измерения:", reply_markup=units_kb)
        await state.set_state(AddProduct.unit)
        
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число!")

# === ОБРАБОТКА ВЫБОРА ЕДИНИЦЫ ИЗМЕРЕНИЯ (ОТДЕЛЬНО!) ===
@dp.callback_query(F.data.startswith("select_unit_"))
async def process_unit_selection(callback: types.CallbackQuery, state: FSMContext):
    unit_map = {
        "piece": "штука",
        "half": "пол-литра",
        "pack": "пачка",
        "bottle": "бутылка",
        "plate": "блюдо"
    }
    
    unit = unit_map[callback.data.split("_")[2]]  # select_unit_ + название
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ Готово! `{name}`: {qty} {unit}")
    await state.clear()
    await cmd_start(callback.message)

# === ОБЩИЙ ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ КНОПОК ===
@dp.callback_query(F.data.startswith(("dec_", "inc_", "del_", "add_product", "refresh_list", "low_qty", "i")))
async def handle_all_buttons(callback: types.CallbackQuery):
    """ОБРАБОТЧИК ДЛЯ ОСНОВНЫХ ФУНКЦИОНАЛЬНЫХ КНОПОК"""
    try:
        data = callback.data
        
        if data.startswith("add_product"):  # Добавление продукта
            await callback.answer("Открываю добавление...", show_alert=False)
            await start_add_process(callback.message, FSMContext(bot.storage))
            
        elif data.startswith("dec_") or data.startswith("inc_") or data.startswith("del_"):  # Изменение количества
            action = data.split("_")[1][0]  # d или i
            name = unquote(data.split("_", 2)[1])
            
            if action == "d":  # minus
                new_qty = await database.change_quantity(name, -1)
                await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
                
            elif action == "i":  # plus
                new_qty = await database.change_quantity(name, 1)
                await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
                
            elif action == "d":  # delete
                await database.delete_product(name)
                await callback.answer(f"✓ {name} удален", show_alert=False)
            
            await refresh_last_message(callback.from_user.id)
            
        elif data == "refresh_list":  # Обновить список
            await callback.answer("Обновляю...", show_alert=False)
            await refresh_last_message(callback.from_user.id)
            
        elif data == "low_qty":  # Показать мало продуктов
            await callback.answer("Показываю продукты с низким запасом...", show_alert=False)
            await show_low_quantity_list(callback.from_user.id)
            
        elif data == "i":  # Инфо (ничего не делаем)
            await callback.answer("Ничего не делать", show_alert=True)
            
    except Exception as e:
        logging.error(f"Ошибка кнопки: {e}")
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

async def show_low_quantity_list(user_id):
    products = await database.get_all_products()
    low_products = [(name, qty, unit) for name, qty, unit in products if float(qty) <= 1]
    
    if not low_products:
        text = "✅ Все продукты в нормальном количестве!"
        kb = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh_list")]]
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
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
            InlineKeyboardButton(text=f"{name}", callback_data="i"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="low_qty")])
    keyboard.append([InlineKeyboardButton(text="➡️ Добавить продукт", callback_data="add_product")])
    
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
                InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
                InlineKeyboardButton(text=f"{name}", callback_data="i"),
                InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
                InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
            ]
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
        keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="low_qty")])
        keyboard.append([InlineKeyboardButton(text="➡️ Добавить продукт", callback_data="add_product")])
        
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
