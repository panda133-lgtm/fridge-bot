import asyncio, logging, os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
from urllib.parse import quote, unquote

import database

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher()

class AddProduct(StatesGroup):
    name = State()
    quantity = State()
    unit = State()

# Главное меню (всегда внизу)
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]
    ], resize_keyboard=True)

# Клавиатура для списка (возле каждого продукта + общие кнопки)
def product_list_kb(products):
    kb = []
    for name, qty, unit in products:
        safe = quote(name)  # безопасный ID для callback
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"dec_{safe}"),
            InlineKeyboardButton(text=name, callback_data="skip"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{safe}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{safe}")
        ])
    kb.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh")])
    kb.append([InlineKeyboardButton(text="📉 Мало продуктов (≤3)", callback_data="low")])
    kb.append([InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_new")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

# Функция отправки списка (всегда создаёт НОВОЕ сообщение)
async def send_list(target):
    products = await database.get_all_products()
    if not products:
        await target.answer("❌ Список пуст. Нажмите ➕ чтобы добавить.", reply_markup=main_kb())
        return

    text = "📋 **Ваши продукты:**\n\n"
    for name, qty, unit in products[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"

    await target.answer(text, parse_mode="Markdown", reply_markup=product_list_kb(products))

# === СТАРТ И ГЛАВНОЕ МЕНЮ ===
@dp.message(Command("start"))
async def start_cmd(msg: types.Message):
    await msg.answer("Привет! Я ваш Умный Холодильник 🧊\nВыберите действие:", reply_markup=main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def list_cmd(msg: types.Message):
    await send_list(msg)

# === ДОБАВЛЕНИЕ ПРОДУКТА ===
@dp.callback_query(F.data == "add_new")
async def add_start(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer()
    await cb.message.answer("📝 Напишите название продукта:", reply_markup=main_kb())
    await state.set_state(AddProduct.name)

@dp.message(AddProduct.name)
async def add_name(msg: types.Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await msg.answer("🔢 Напишите количество (можно дробь, например 0.5 или 3):", reply_markup=main_kb())
    await state.set_state(AddProduct.quantity)

@dp.message(AddProduct.quantity)
async def add_qty(msg: types.Message, state: FSMContext):
    try:
        val = float(msg.text.replace(',', '.'))
        await state.update_data(quantity=val)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🍏 Штука", callback_data="u_pcs")],
            [InlineKeyboardButton(text="🥛 Литр", callback_data="u_lit")],
            [InlineKeyboardButton(text="🧱 Пачка", callback_data="u_pac")],
            [InlineKeyboardButton(text="🍶 Бутылка", callback_data="u_btl")],
            [InlineKeyboardButton(text="🥗 Блюдо", callback_data="u_plt")]
        ])
        await msg.answer("📏 Выберите единицу:", reply_markup=kb)
        await state.set_state(AddProduct.unit)
    except:
        await msg.answer("❌ Введите корректное число!", reply_markup=main_kb())

@dp.callback_query(F.data.startswith("u_"))
async def add_unit(cb: types.CallbackQuery, state: FSMContext):
    units = {"pcs": "шт.", "lit": "л.", "pac": "уп.", "btl": "бут.", "plt": "блюд"}
    unit = units[cb.data.split("_")[1]]
    data = await state.get_data()
    await database.add_or_update_product(data['name'], data['quantity'], unit)
    await cb.message.delete()
    await cb.message.answer(f"✅ Добавлено: `{data['name']}`: {data['quantity']} {unit}", parse_mode="Markdown")
    await state.clear()
    await send_list(cb)  # Отправляем обновлённый список

# === ОБРАБОТКА КНОПОК В СПИСКЕ (➖ ➕ 🗑) ===
@dp.callback_query(F.data.startswith(("dec_", "inc_", "del_")))
async def handle_qty(cb: types.CallbackQuery):
    parts = cb.data.split("_", 1)
    act, raw_name = parts[0], parts[1]
    name = unquote(raw_name)

    if act == "del":
        await database.delete_product(name)
        await cb.answer(f"🗑 {name} удален", show_alert=False)
    elif act == "inc":
        await database.change_quantity(name, 1)
        await cb.answer(f"➕ {name} +1", show_alert=False)
    elif act == "dec":
        await database.change_quantity(name, -1)
        await cb.answer(f"➖ {name} -1", show_alert=False)

    await send_list(cb)  # Всегда отправляем НОВЫЙ список с новыми кнопками

@dp.callback_query(F.data == "skip")
async def skip_cb(cb: types.CallbackQuery):
    await cb.answer()

@dp.callback_query(F.data == "refresh")
async def refresh_cb(cb: types.CallbackQuery):
    await cb.answer("🔄 Список обновлён")
    await send_list(cb)

@dp.callback_query(F.data == "low")
async def low_cb(cb: types.CallbackQuery):
    products = await database.get_all_products()
    low = [(n,q,u) for n,q,u in products if float(q) <= 3]
    if not low:
        await cb.message.answer("✅ Все продукты в норме (>3)")
    else:
        txt = "📉 **Осталось мало (≤3):**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n,q,u in low)
        await cb.message.answer(txt, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="refresh")]]))
    await cb.answer()

# === ЗАПУСК ===
async def main():
    await database.init_db()
    print("✅ База готова. Бот запущен!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
