import asyncio
import logging
import os
from urllib.parse import quote, unquote

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv

import database

# ================= НАСТРОЙКИ =================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ Переменная BOT_TOKEN не найдена в .env!")

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
    """Две главные кнопки внизу экрана"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]],
        resize_keyboard=True
    )

def get_list_keyboard(products):
    """Кнопки управления рядом с каждым продуктом + общие"""
    buttons = []
    for name, qty, unit in products:
        safe_name = quote(name)  # Кодируем имя для безопасного callback
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec:{safe_name}"),
            InlineKeyboardButton(text=f"{name} ({qty} {unit})", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"inc:{safe_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del:{safe_name}")
        ]
        buttons.append(row)

    # Нижние общие кнопки
    buttons.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh")])
    buttons.append([InlineKeyboardButton(text="📉 Мало продуктов (≤3)", callback_data="show_low")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить продукт", callback_data="add_from_list")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ =================
async def send_full_list(chat_id: int):
    """Формирует и отправляет актуальный список. Всегда создаёт НОВОЕ сообщение."""
    products = await database.get_all_products()

    if not products:
        await bot.send_message(
            chat_id=chat_id,
            text="❌ Список пуст. Нажмите ➕ чтобы добавить.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕ Добавить", callback_data="add_from_list")]])
        )
        return

    text = "📋 **Актуальный список:**\n\n"
    for name, qty, unit in products[:50]:
        icon = "⚠️" if float(qty) <= 3 else "✅"
        text += f"{icon} `{name}`: {qty} {unit}\n"

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=get_list_keyboard(products)
    )

# ================= ОБРАБОТЧИКИ =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("Привет! Я Умный Холодильник 🧊\nУправляйте запасами через кнопки ниже:", reply_markup=get_main_keyboard())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список продуктов")
async def cmd_list(message: types.Message):
    await send_full_list(message.chat.id)

# --- Добавление продукта ---
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
        await message.answer("❌ Пожалуйста, введите корректное число!", reply_markup=get_main_keyboard())
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
    await database.add_or_update_product(data['name'], data['quantity'], unit)

    await callback.message.answer(f"✅ Готово! `{data['name']}`: {data['quantity']} {unit}", parse_mode="Markdown")
    await state.clear()
    await send_full_list(callback.message.chat.id)

# --- Кнопки внутри списка (➖ ➕ 🗑) ---
@dp.callback_query(F.data.startswith(("dec:", "inc:", "del:")))
async def cb_list_actions(callback: types.CallbackQuery):
    await callback.answer()
    action, safe_name = callback.data.split(":", 1)
    name = unquote(safe_name)

    try:
        if action == "dec":
            await database.change_quantity(name, -1)
            await callback.answer(f"➖ {name}: -1")
        elif action == "inc":
            await database.change_quantity(name, 1)
            await callback.answer(f"➕ {name}: +1")
        elif action == "del":
            await database.delete_product(name)
            await callback.answer(f"🗑 {name} удалён")

        # Всегда отправляем обновлённый список после действия
        await send_full_list(callback.message.chat.id)
    except Exception as e:
        logging.error(f"Ошибка действия: {e}")
        await callback.message.answer("❌ Произошла ошибка. Попробуйте снова.")

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
    low_products = [(n, q, u) for n, q, u in products if float(q) <= 3]

    if not low_products:
        await callback.message.answer("✅ Все продукты в норме! (>3)")
    else:
        text = "📉 **Осталось мало (≤3):**\n\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n, q, u in low_products)
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 К полному списку", callback_data="refresh")]
        ]))

# ================= ЗАПУСК =================
async def main():
    await database.init_db()
    print("✅ База данных инициализирована. Бот запущен...")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен вручную.")
