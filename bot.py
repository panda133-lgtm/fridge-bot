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

# Импорт наших модулей
import database
import keyboards

# Загрузка переменных из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в файле .env!")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Машина состояний
class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

# Размер чанка для разбивки списка
CHUNK_SIZE = 20

# Глобальные переменные для уведомлений
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

# Показать список
@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    
    if not products:
        text = f"❌ Холодильник пуст! Добавьте что-нибудь."
        keyboard = [[InlineKeyboardButton(text="➕ Добавить вручную", callback_data="add_manual")]]
        await message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
        return
    
    chunks = [products[i:i+CHUNK_SIZE] for i in range(0, len(products), CHUNK_SIZE)]
    
    for i, chunk in enumerate(chunks[:5]):
        await send_list_chunk(message, chunk, current=i+1, total=len(chunks))
    
    if len(chunks) > 5:
        await asyncio.sleep(1.5)
        for chunk in chunks[5:]:
            await send_list_chunk(message, chunk)

# Отправка одного куска списка
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
            InlineKeyboardButton(text=f"{name} ({qty} {unit})", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="show_low_quantity")])
    
    await message.answer(
        text, 
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

# Добавить продукт
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
        await message.answer("Выберите единицу измерения:")
        
        # Кнопки выбора единиц измерения
        units_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука/шт.", callback_data="unit_piece")],
            [InlineKeyboardButton(text="🥛 Пол-литра/шт.", callback_data="unit_half")],
            [InlineKeyboardButton(text="🧱 Пачка/пакет", callback_data="unit_pack")],
            [InlineKeyboardButton(text="🍶 Бутылка/л", callback_data="unit_bottle")],
            [InlineKeyboardButton(text="🥗 Тарелка/блюдо", callback_data="unit_plate")]
        ])
        
        await message.answer("Выберите единицу измерения:", reply_markup=units_kb)
        await state.set_state(AddProduct.unit)
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число!")

# Выбор единицы измерения
@dp.callback_query(F.data.startswith("unit_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    unit_map = {
        "piece": "штука",
        "half": "пол-литра",
        "pack": "пачка",
        "bottle": "бутылка",
        "plate": "блюдо"
    }
    
    unit = unit_map[callback.data.split("_")[1]]
    data = await state.get_data()
    name = data['name']
    qty = data['quantity']
    
    await database.add_or_update_product(name, str(qty), unit)
    await bot.send_message(chat_id=callback.from_user.id, text=f"✅ Готово! `{name}`: {qty} {unit}")
    await state.clear()

# === ОБРАБОТКА КНОПОК ===

async def handle_quantity_change(callback, operation, amount):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        new_qty = await database.change_quantity(name, amount)
        await callback.answer(f"✓ {name}: {new_qty}", show_alert=False)
        
        await refresh_last_message(callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        logging.error(f"Operation error: {e}")

@dp.callback_query(F.data.startswith("inc_"))
async def increase_qty(callback: types.CallbackQuery):
    await handle_quantity_change(callback, 'inc', 1)

@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    await handle_quantity_change(callback, 'dec', -1)

@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    try:
        name = unquote(callback.data.split("_", 1)[1])
        await database.delete_product(name)
        await callback.answer(f"✓ {name} удален", show_alert=False)
        
        await refresh_last_message(callback.from_user.id)
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        logging.error(f"Delete error: {e}")

# Сохранение ID последнего сообщения от пользователя
user_last_messages = {}

@dp.callback_query(F.data == "refresh_list")
async def refresh_list(callback: types.CallbackQuery):
    await callback.answer("Обновляю...", show_alert=False)
    await refresh_last_message(callback.from_user.id)

@dp.callback_query(F.data == "show_low_quantity")
async def show_low_quantity(callback: types.CallbackQuery):
    await callback.answer("Показываю продукты с низким запасом...")
    await show_low_quantity_list(callback.from_user.id)

async def show_low_quantity_list(user_id):
    products = await database.get_all_products()
    low_products = [(name, qty, unit) for name, qty, unit in products if float(qty) <= 1]
    
    if not low_products:
        text = "✅ Все продукты в нормальном количестве!"
        keyboard = [[InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh_list")]]
        await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))
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
            InlineKeyboardButton(text=f"{name} ({qty} {unit})", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data="refresh_list")])
    
    await bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

# Обновление списка (общая функция)
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
                InlineKeyboardButton(text=f"{name} ({qty} {unit})", callback_data="info"),
                InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
                InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
            ]
            keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
        keyboard.append([InlineKeyboardButton(text="📉 Мало продуктов", callback_data="show_low_quantity")])
        
        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
        )
                
    except Exception as e:
        print(f"Ошибка при обновлении: {e}")

# === АВТОМАТИЧЕСКИЕ УВЕДОМЛЕНИЯ ===
async def notification_worker():
    """Фоновый процесс проверки уведомлений"""
    global last_notification_check_day
    
    # Время проверок МСК → UTC: 14:00, 17:00, 17:30 → 11:00, 16:00, 16:30
    notification_hours = [11, 16, 16]  
    notification_minutes = ["00", "00", "30"]  
    
    while True:
        try:
            now = datetime.now()
            
            for idx, check_hour in enumerate(notification_hours):
                target_minute = notification_minutes[idx]
                
                if now.hour == check_hour and now.minute >= int(target_minute):
                    if now.day != last_notification_check_day:
                        last_notification_check_day = now.day
                        try:
                            await check_low_quantity_notifications()
                        except Exception as e:
                            logging.error(f"Ошибка уведомления: {e}")
                        break
            
            await asyncio.sleep(300)  # Проверка каждые 5 минут
            
        except Exception as e:
            logging.error(f"Ошибка цикла уведомлений: {e}")

async def check_low_quantity_notifications():
    """Проверяет наличие продуктов с малым количеством и отправляет уведомления админу"""
    try:
        products = await database.get_all_products()
        low_products = [(name, qty, unit) for name, qty, unit in products if float(qty) <= 1]
        
        if not low_products:
            return
        
        now = datetime.now().strftime("%H:%M")
        
        text = f"⚠️ *НАПОМИНАНИЕ О ПРОДУКТАХ* ⚠️\n\n"
        text += f"⏰ Время: {now}\n\n"
        text += "📉 *Осталось мало:* \n"
        
        for name, qty, unit in low_products:
            text += f"• `{name}`: {qty} {unit}\n"
        
        text += "\n🛒 Порекомендуем купить эти продукты!"
        
        await bot.send_message(chat_id=ADMIN_ID, text=text, parse_mode="Markdown")
        logging.info(f"Уведомление отправлено на {now}")
        
    except Exception as e:
        logging.error(f"Ошибка проверки уведомлений: {e}")

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
        print("База данных готова")
    except Exception as e:
        print(f"Ошибка базы данных: {e}")
        print("Бот будет работать без сохранения данных")
    
    print("🤖 Бот запущен...")
    
    asyncio.create_task(start_health_server())
    asyncio.create_task(notification_worker())
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")
