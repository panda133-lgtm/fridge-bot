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
ADMIN_ID = int(os.getenv("ADMIN_ID"))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

def get_main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]
    ], resize_keyboard=True)

def get_product_keyboard(products):
    """Создаёт кнопки используя ID продуктов (короткие и безопасные)"""
    kb = []
    for prod_id, name, qty, unit in products:
        # Используем ID (число) вместо имени - это коротко и безопасно!
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"d_{prod_id}"),
            InlineKeyboardButton(text=name, callback_data="i"),
            InlineKeyboardButton(text="➕", callback_data=f"i_{prod_id}"),
            InlineKeyboardButton(text="🗑", callback_data=f"x_{prod_id}")
        ])
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="r")])
    kb.append([InlineKeyboardButton(text="📉 Мало (<3)", callback_data="l")])
    kb.append([InlineKeyboardButton(text="➕ Новый", callback_data="a")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! 🧊\n\nЧто делаем?", reply_markup=get_main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(message: types.Message):
    products = await database.get_all_products()
    if not products:
        await message.answer("❌ Пуст!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="a")]]))
        return
    
    text = f"📋 **Список ({len(products)}):**\n\n"
    for prod_id, name, qty, unit in products[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"
    
    markup = get_product_keyboard(products)
    await message.answer(text, parse_mode="Markdown", reply_markup=markup)

@dp.callback_query(F.data == "a")
async def add_product(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer("")
    await callback.message.reply("Название:", reply_markup=get_main_kb())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def process_name(message: types.Message, state: FSMContext):
    if not message.text.strip():
        await message.answer("⚠️ Введите название!", reply_markup=get_main_kb())
        return
    await state.update_data(name=message.text.strip())
    await message.answer("Количество:", reply_markup=get_main_kb())
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
        await message.answer("❌ Число!", reply_markup=get_main_kb())

@dp.callback_query(F.data.startswith("u_"))
async def process_unit(callback: types.CallbackQuery, state: FSMContext):
    map_unit = {"pie": "штука", "lit": "литр", "pack": "пачка", "bot": "бутылка", "plt": "блюдо"}
    unit = map_unit[callback.data.split("_")[1]]
    data = await state.get_data()
    await database.add_or_update_product(data['name'], str(data['quantity']), unit)
    await callback.message.delete()
    await callback.message.answer(f"✅ {data['name']}: {data['quantity']} {unit}")
    await state.clear()
    await refresh(callback.from_user.id, callback.message.chat.id)

# === ОБРАБОТКА КНОПОК С ID ПРОДУКТОВ ===
@dp.callback_query(F.data.startswith("d_"))  # Уменьшить
async def dec_qty(callback: types.CallbackQuery):
    try:
        prod_id = int(callback.data.split("_")[1])
        await database.change_quantity_by_id(prod_id, -1)
        await callback.answer("✓", show_alert=False)
        await refresh(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("i_"))  # Увеличить
async def inc_qty(callback: types.CallbackQuery):
    try:
        prod_id = int(callback.data.split("_")[1])
        await database.change_quantity_by_id(prod_id, 1)
        await callback.answer("✓", show_alert=False)
        await refresh(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data.startswith("x_"))  # Удалить
async def delete_item(callback: types.CallbackQuery):
    try:
        prod_id = int(callback.data.split("_")[1])
        await database.delete_product_by_id(prod_id)
        await callback.answer("✓ Удален", show_alert=False)
        await refresh(callback.from_user.id, callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        await callback.answer("Ошибка", show_alert=True)

@dp.callback_query(F.data == "i")  # Инфо (пустая кнопка)
async def info(callback: types.CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data == "r")  # Обновить
async def refresh_btn(callback: types.CallbackQuery):
    await callback.answer("🔄")
    await refresh(callback.from_user.id, callback.message.chat.id)

@dp.callback_query(F.data == "l")  # Мало
async def low_q(callback: types.CallbackQuery):
    products = await database.get_all_products()
    low = [(pid, n, q, u) for pid, n, q, u in products if float(q) <= 3]
    if not low:
        await callback.message.answer("✅ Всё ок (>3)")
    else:
        text = "📉 **Мало:**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for _, n, q, u in low)
        await callback.message.answer(text, parse_mode="Markdown")
    await callback.answer()

async def refresh(user_id, chat_id):
    products = await database.get_all_products()
    if not products:
        await bot.send_message(chat_id, "❌ Пуст", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕", callback_data="a")]]))
        return
    text = f"📋 **Список:**\n\n" + "\n".join(f"{'⚠️' if float(q)<=3 else '✅'} `{n}`: {q} {u}" for _, n, q, u in products[:50])
    markup = get_product_keyboard(products)
    await bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)

async def main():
    await database.init_db()
    print("🤖 Запущен!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == '__main__':
    asyncio.run(main())
