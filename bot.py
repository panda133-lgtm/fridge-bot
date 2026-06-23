"""
Умный Холодильник — бот для учёта продуктов
Время обновления только при изменениях
"""
import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiohttp import web
from dotenv import load_dotenv

import database

# ================= НАСТРОЙКИ =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не найдена!")

PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= СОСТОЯНИЯ =================
class AddProductFSM(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

# ================= КЛАВИАТУРЫ =================
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")],
            [KeyboardButton(text="🕐 Время обновления")]
        ],
        resize_keyboard=True
    )

def get_list_keyboard(products):
    buttons = []
    for product_id, name, qty, unit in products:
        buttons.append([
            InlineKeyboardButton(text="➖", callback_data=f"dec:{product_id}"),
            InlineKeyboardButton(text=f"{name}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"inc:{product_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{product_id}")
        ])
    buttons.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh")])
    buttons.append([InlineKeyboardButton(text="📉 Мало продуктов (≤3)", callback_data="show_low")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_from_list")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
async def send_full_list(chat_id: int):
    """Показывает список БЕЗ обновления времени (только просмотр)"""
    products = await database.get_all_products()
    
    if not products:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Список пуст. Нажмите ➕ чтобы добавить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_from_list")]])
        )
        return
    
    text = "📋 **Актуальный список:**\n\n"
    for product_id, name, qty, unit in products[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=get_list_keyboard(products)
    )

# ================= HEALTH-СЕРВЕР =================
async def handle_health(request):
    return web.Response(text="Bot is running! 🧊")

async def start_health_server():
    app = web.Application()
    app.router.add_get('/', handle_health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logging.info(f"🏥 Health server запущен на порту {PORT}")

# ================= КОМАНДЫ =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await database.save_user_chat_id(message.chat.id)
    await message.answer(
        "Привет! Я Умный Холодильник 🧊\nУправляйте запасами через кнопки ниже:",
        reply_markup=get_main_keyboard()
    )

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def cmd_list(message: types.Message):
    await send_full_list(message.chat.id)

@dp.message(F.text == "🕐 Время обновления")
async def show_last_update_btn(message: types.Message):
    last_time = database.get_last_update_time()
    if last_time:
        await message.answer(
            f"🕐 Последний раз список менялся: **{last_time.strftime('%d.%m.%Y в %H:%M')}**",
            parse_mode="Markdown"
        )
    else:
        await message.answer("🕐 В этой сессии список ещё не менялся.")

# ================= ДОБАВЛЕНИЕ ПРОДУКТА =================
@dp.message(F.text == "➕ Добавить продукт")
async def add_from_main_menu(message: types.Message, state: FSMContext):
    await message.answer("📝 Напишите название продукта:", reply_markup=get_main_keyboard())
    await state.set_state(AddProductFSM.name)

@dp.callback_query(F.data == "add_from_list")
async def cb_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer("📝 Напишите название продукта:", reply_markup=get_main_keyboard())
    await state.set_state(AddProductFSM.name)

@dp.message(AddProductFSM.name)
async def msg_add_name(message: types.Message, state: FSMContext):
    if not message.text.strip():
        await message.answer("⚠️ Введите корректное название!", reply_markup=get_main_keyboard())
        return
    await state.update_data(name=message.text.strip())
    await message.answer("🔢 Введите количество (можно дробь, например 0.5 или 2):", reply_markup=get_main_keyboard())
    await state.set_state(AddProductFSM.quantity)

@dp.message(AddProductFSM.quantity)
async def msg_add_qty(message: types.Message, state: FSMContext):
    try:
        qty = float(message.text.replace(',', '.'))
        await state.update_data(quantity=qty)
    except ValueError:
        await message.answer("❌ Введите корректное число!", reply_markup=get_main_keyboard())
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍏 Штука", callback_data="unit:шт.")],
        [InlineKeyboardButton(text="🥛 Литр", callback_data="unit:л.")],
        [InlineKeyboardButton(text="🧱 Пачка", callback_data="unit:уп.")],
        [InlineKeyboardButton(text="🍶 Бутылка", callback_data="unit:бут.")],
        [InlineKeyboardButton(text="🥗 Блюдо", callback_data="unit:блюд.")]
    ])
    await message.answer("📏 Выберите единицу измерения:", reply_markup=kb)
    await state.set_state(AddProductFSM.unit)

@dp.callback_query(F.data.startswith("unit:"))
async def cb_add_unit(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    unit = callback.data.split(":")[1]
    data = await state.get_data()
    
    if 'name' not in data or 'quantity' not in data:
        await callback.message.answer("❌ Ошибка. Начни заново.")
        await state.clear()
        return
    
    try:
        success = await database.add_or_update_product(data['name'], data['quantity'], unit)
        if success:
            # ✅ ВРЕМЯ ОБНОВЛЯЕТСЯ ТОЛЬКО ПРИ ДОБАВЛЕНИИ!
            database.set_last_update_time()
            await callback.message.answer(
                f"✅ Готово! `{data['name']}`: {data['quantity']} {unit}",
                parse_mode="Markdown"
            )
            await state.clear()
            await send_full_list(callback.message.chat.id)
        else:
            await callback.message.answer("❌ Не удалось сохранить. Попробуй ещё раз.")
            await state.clear()
    except Exception as e:
        logging.error(f"Ошибка сохранения: {e}")
        await callback.message.answer("❌ Не удалось сохранить.")
        await state.clear()

# ================= КНОПКИ СПИСКА =================
@dp.callback_query(F.data.startswith(("dec:", "inc:", "del:")))
async def cb_list_actions(callback: types.CallbackQuery):
    await callback.answer()
    action, product_id_str = callback.data.split(":", 1)
    product_id = int(product_id_str)
    
    try:
        success = False
        if action == "dec":
            result = await database.change_quantity_by_id(product_id, -1)
            if result > 0:
                success = True
            await callback.answer("➖ -1")
        elif action == "inc":
            result = await database.change_quantity_by_id(product_id, 1)
            if result > 0:
                success = True
            await callback.answer("➕ +1")
        elif action == "del":
            success = await database.delete_product_by_id(product_id)
            await callback.answer("🗑 Удалён")
        
        # ✅ ВРЕМЯ ОБНОВЛЯЕТСЯ ТОЛЬКО ПРИ ИЗМЕНЕНИИ!
        if success:
            database.set_last_update_time()
        
        await send_full_list(callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.message.answer("❌ Ошибка. Попробуйте снова.")

@dp.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "refresh")
async def cb_refresh(callback: types.CallbackQuery):
    await callback.answer("🔄 Список обновлён!")
    await send_full_list(callback.message.chat.id)

@dp.callback_query(F.data == "show_low")
async def cb_show_low(callback: types.CallbackQuery):
    await callback.answer()
    products = await database.get_all_products()
    low_products = [(pid, n, q, u) for pid, n, q, u in products if float(q) <= 3]
    
    if not low_products:
        await callback.message.answer("✅ Все продукты в норме! (>3)")
    else:
        text = "📉 **Осталось мало (≤3):**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for _, n, q, u in low_products)
        await callback.message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 К списку", callback_data="refresh")]])
        )

# ================= УВЕДОМЛЕНИЯ =================
async def send_low_stock_notifications():
    logging.info("🔔 Проверка низкого запаса...")
    try:
        low_products = await database.get_low_stock_products(threshold=3.0)
        if not low_products:
            logging.info("✅ Все продукты в норме")
            return
        
        text = "🚨 **Внимание! Заканчиваются продукты:**\n\n"
        for name, qty, unit in low_products:
            text += f"⚠️ `{name}`: осталось {qty} {unit}\n"
        text += "\nПополните запасы! 🛒"
        
        chat_ids = await database.get_all_user_chat_ids()
        sent = 0
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logging.warning(f"Не удалось отправить в {chat_id}: {e}")
        logging.info(f"🔔 Уведомлений отправлено: {sent}")
    except Exception as e:
        logging.error(f"❌ Ошибка планировщика: {e}")

async def run_notification_scheduler():
    logging.info("⏰ Планировщик запущен. Проверка каждые 60 сек...")
    while True:
        try:
            now_utc = datetime.now(timezone.utc)
            if now_utc.hour in (11, 15) and now_utc.minute == 0:
                logging.info("🕐 Время рассылки!")
                await send_low_stock_notifications()
                await asyncio.sleep(65)
            await asyncio.sleep(30)
        except Exception as e:
            logging.error(f"⚠️ Планировщик: {e}")
            await asyncio.sleep(10)

# ================= ЗАПУСК =================
async def main():
    try:
        await database.init_db()
        logging.info("✅ База данных инициализирована.")
        
        await start_health_server()
        
        logging.info("⏳ Ждём освобождения сессии Telegram...")
        await asyncio.sleep(3)
        
        asyncio.create_task(run_notification_scheduler())
        
        logging.info("🚀 Запуск polling... Бот готов к работе!")
        await dp.start_polling(bot, drop_pending_updates=True)
    except asyncio.CancelledError:
        logging.info("⏹️ Сигнал остановки.")
    except Exception as e:
        logging.critical(f"💥 Критическая ошибка: {e}")
    finally:
        await bot.session.close()
        logging.info("🔌 Сессия закрыта.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен.")
    except Exception as e:
        logging.critical(f"💥 Бот упал: {e}")
