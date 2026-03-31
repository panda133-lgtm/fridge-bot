import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv

# Импорт наших модулей
import database
import keyboards

# Загрузка переменных из .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# Машина состояний
class AddProduct(StatesGroup):
    name = State()
    quantity = State()


# Команда /start
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
        await message.answer("Холодильник пуст! Добавьте что-нибудь.")
        return

    text = "📋 **Актуальный список:**\n\n"
    for name, qty in products:
        icon = "⚠️" if qty < 3 else "✅"
        text += f"{icon} `{name}`: {qty} шт.\n"

    await message.answer(
        text,
        parse_mode="Markdown",
        reply_markup=keyboards.get_product_list_keyboard(products)
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
    await message.answer("Теперь напиши количество (числом):")
    await state.set_state(AddProduct.quantity)


@dp.message(AddProduct.quantity)
async def process_quantity(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Пожалуйста, введи число!")
        return

    data = await state.get_data()
    name = data['name']
    qty = int(message.text)

    await database.add_or_update_product(name, qty)
    await message.answer(f"✅ Готово! `{name}`: {qty} шт.")
    await state.clear()


# Обработка кнопок +
@dp.callback_query(F.data.startswith("inc_"))
async def increase_qty(callback: types.CallbackQuery):
    name = callback.data.split("_", 1)[1]
    new_qty = await database.change_quantity(name, 1)
    await callback.answer(f"{name}: {new_qty}")
    await edit_list_message(callback)


# Обработка кнопок -
@dp.callback_query(F.data.startswith("dec_"))
async def decrease_qty(callback: types.CallbackQuery):
    name = callback.data.split("_", 1)[1]
    new_qty = await database.change_quantity(name, -1)
    await callback.answer(f"{name}: {new_qty}")
    await edit_list_message(callback)


# Обработка кнопки удалить
@dp.callback_query(F.data.startswith("del_"))
async def delete_item(callback: types.CallbackQuery):
    name = callback.data.split("_", 1)[1]
    await database.delete_product(name)
    await callback.answer(f"{name} удален")
    await edit_list_message(callback)


# Обновить список
@dp.callback_query(F.data == "refresh_list")
async def refresh_list(callback: types.CallbackQuery):
    await edit_list_message(callback)


# Вспомогательная функция
async def edit_list_message(callback: types.CallbackQuery):
    products = await database.get_all_products()
    if not products:
        await callback.message.edit_text("Холодильник пуст!")
        return

    text = "📋 **Актуальный список:**\n\n"
    for name, qty in products:
        icon = "⚠️" if qty < 3 else "✅"
        text += f"{icon} `{name}`: {qty} шт.\n"

    await callback.message.edit_text(
        text,
        parse_mode="Markdown",
        reply_markup=keyboards.get_product_list_keyboard(products)
    )


# Запуск
async def main():
    await database.init_db()
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен")