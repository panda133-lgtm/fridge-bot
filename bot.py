import asyncio, logging, os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
import database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден!")
if not DATABASE_URL:
    print("⚠️ DATABASE_URL не найден! Продукты не будут сохраняться!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AddFSM(StatesGroup):
    name = State()
    qty = State()
    unit = State()

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]], resize_keyboard=True)

def list_kb(products):
    kb = []
    for pid, name, qty, unit in products:
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"d:{pid}"),
            InlineKeyboardButton(text=f"{name}", callback_data="i"),
            InlineKeyboardButton(text="➕", callback_data=f"i:{pid}"),
            InlineKeyboardButton(text="🗑", callback_data=f"x:{pid}")
        ])
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="r")])
    kb.append([InlineKeyboardButton(text="📉 Мало", callback_data="l")])
    kb.append([InlineKeyboardButton(text="➕ Добавить", callback_data="a")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def send_list(chat_id):
    """Отправляет список продуктов"""
    prods = await database.get_all_products()
    logging.info(f"📋 В базе {len(prods)} продуктов")
    
    if not prods:
        await bot.send_message(
            chat_id, 
            "❌ Список пуст!\n\nНажми ➕ Добавить чтобы добавить продукт.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить продукт", callback_data="a")]])
        )
        return
    
    txt = "📋 **Ваши продукты:**\n\n"
    for _, name, qty, unit in prods[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        txt += f"{icon} `{name}`: {qty} {unit}\n"
    
    await bot.send_message(chat_id, txt, parse_mode="Markdown", reply_markup=list_kb(prods))

@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("Привет! Я Умный Холодильник 🧊\n\nЖми кнопки внизу:", reply_markup=main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(m: types.Message):
    await send_list(m.chat.id)

# === ДОБАВЛЕНИЕ ПРОДУКТА ===
@dp.callback_query(F.data == "a")
async def add_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("📝 **Напиши название продукта** (например: Молоко):", parse_mode="Markdown", reply_markup=main_kb())
    await state.set_state(AddFSM.name)

@dp.message(AddFSM.name)
async def add_name(m: types.Message, state: FSMContext):
    name = m.text.strip()
    if not name:
        await m.answer("⚠️ Введите название!", reply_markup=main_kb())
        return
    
    await state.update_data(name=name)
    await m.answer(f"🔢 **Введите количество** для '{name}':\n\n(можно дробь: 0.5, 2, 3.5)", parse_mode="Markdown", reply_markup=main_kb())
    await state.set_state(AddFSM.qty)

@dp.message(AddFSM.qty)
async def add_qty(m: types.Message, state: FSMContext):
    try:
        qty = float(m.text.replace(',', '.'))
        await state.update_data(qty=qty)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука", callback_data="u:шт.")],
            [InlineKeyboardButton(text="🥛 Литр", callback_data="u:л.")],
            [InlineKeyboardButton(text="🧱 Пачка", callback_data="u:уп.")],
            [InlineKeyboardButton(text="🍶 Бутылка", callback_data="u:бут.")],
            [InlineKeyboardButton(text="🥗 Блюдо", callback_data="u:блюд.")]
        ])
        await m.answer("📏 **Выберите единицу измерения**:", parse_mode="Markdown", reply_markup=kb)
        await state.set_state(AddFSM.unit)
    except ValueError:
        await m.answer("❌ **Введите корректное число!**\n\nНапример: 1, 2.5, 0.5", parse_mode="Markdown", reply_markup=main_kb())

@dp.callback_query(F.data.startswith("u:"))
async def add_unit(cb: types.CallbackQuery, state: FSMContext):
    unit = cb.data.split(":")[1]
    data = await state.get_data()
    name = data['name']
    qty = data['qty']
    
    # Сохраняем в базу
    try:
        await database.add_or_update_product(name, qty, unit)
        logging.info(f"✅ Добавлен продукт: {name} {qty} {unit}")
        
        # Отправляем подтверждение
        await cb.message.answer(f"✅ **Добавлено:**\n`{name}`: {qty} {unit}", parse_mode="Markdown")
        
        # Показываем обновлённый список
        await send_list(cb.message.chat.id)
        
    except Exception as e:
        logging.error(f"❌ Ошибка добавления: {e}")
        await cb.message.answer(f"❌ Ошибка: {e}")
    
    await state.clear()

# === КНОПКИ СПИСКА ===
@dp.callback_query(F.data.startswith(("d:", "i:", "x:")))
async def handle_action(cb: types.CallbackQuery):
    act, pid_str = cb.data.split(":")
    try:
        pid = int(pid_str)
        
        if act == "d":  # Уменьшить
            await database.change_quantity_by_id(pid, -1)
            await cb.answer("➖ -1", show_alert=False)
        elif act == "i":  # Увеличить
            await database.change_quantity_by_id(pid, 1)
            await cb.answer("➕ +1", show_alert=False)
        elif act == "x":  # Удалить
            await database.delete_product_by_id(pid)
            await cb.answer("🗑 Удалено", show_alert=False)
        
        # Показываем обновлённый список
        await send_list(cb.message.chat.id)
        
    except Exception as e:
        logging.error(f"❌ Ошибка: {e}")
        await cb.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "r")  # Обновить
async def refresh(cb: types.CallbackQuery):
    await cb.answer("🔄 Обновляю...", show_alert=False)
    await send_list(cb.message.chat.id)

@dp.callback_query(F.data == "l")  # Мало
async def show_low(cb: types.CallbackQuery):
    prods = await database.get_all_products()
    low = [(n, q, u) for _, n, q, u in prods if float(q) <= 3]
    
    if not low:
        txt = "✅ **Все продукты в норме!**\n\n(>3 шт.)"
    else:
        txt = "📉 **Мало осталось (≤3):**\n\n"
        for n, q, u in low:
            txt += f"⚠️ `{n}`: {q} {u}\n"
    
    await cb.message.answer(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 К списку", callback_data="r")]
    ]))
    await cb.answer()

@dp.callback_query(F.data == "i")  # Инфо (пустая кнопка с названием)
async def info(cb: types.CallbackQuery):
    await cb.answer()

# === ЗАПУСК ===
async def main():
    logging.info("🔧 Инициализация базы данных...")
    await database.init_db()
    logging.info("✅ База готова!")
    logging.info("🤖 Запуск бота...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен")
