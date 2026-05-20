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
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден!")

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
    kb.append([InlineKeyboardButton(text="🔄", callback_data="r")])
    kb.append([InlineKeyboardButton(text="📉 Мало", callback_data="l")])
    kb.append([InlineKeyboardButton(text="➕ Новый", callback_data="a")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def send_list(chat_id):
    prods = await database.get_all_products()
    if not prods:
        await bot.send_message(chat_id, "❌ Пуст", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➕", callback_data="a")]]))
        return
    txt = "📋 **Список:**\n" + "\n".join(f"{'⚠️' if float(q)<=3 else '✅'} `{n}`: {q} {u}" for _,n,q,u in prods[:50])
    await bot.send_message(chat_id, txt, parse_mode="Markdown", reply_markup=list_kb(prods))

@dp.message(Command("start"))
async def start(m: types.Message):
    await m.answer("Привет! 🧊", reply_markup=main_kb())

@dp.message(Command("list"))
@dp.message(F.text == "📦 Список")
async def show_list(m: types.Message):
    await send_list(m.chat.id)

@dp.message(F.text == "➕ Добавить")
@dp.callback_query(F.data == "a")
async def add_start(event, state: FSMContext):
    if isinstance(event, types.CallbackQuery):
        await event.answer()
        msg = event.message
    else:
        msg = event
    await msg.answer("Название:", reply_markup=main_kb())
    await state.set_state(AddFSM.name)

@dp.message(AddFSM.name)
async def add_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer("Количество:", reply_markup=main_kb())
    await state.set_state(AddFSM.qty)

@dp.message(AddFSM.qty)
async def add_qty(m: types.Message, state: FSMContext):
    try:
        val = float(m.text.replace(',', '.'))
        await state.update_data(qty=val)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="шт", callback_data="u:шт")], [InlineKeyboardButton(text="л", callback_data="u:л")]])
        await m.answer("Единица:", reply_markup=kb)
        await state.set_state(AddFSM.unit)
    except:
        await m.answer("❌ Число!", reply_markup=main_kb())

@dp.callback_query(F.data.startswith("u:"))
async def add_unit(cb: types.CallbackQuery, state: FSMContext):
    unit = cb.data.split(":")[1]
    data = await state.get_data()
    await database.add_or_update_product(data['name'], data['qty'], unit)
    await cb.message.answer(f"✅ {data['name']}: {data['qty']} {unit}")
    await state.clear()
    await send_list(cb.message.chat.id)

@dp.callback_query(F.data.startswith(("d:", "i:", "x:")))
async def handle(cb: types.CallbackQuery):
    act, pid = cb.data.split(":")
    pid = int(pid)
    if act == "d": await database.change_quantity_by_id(pid, -1)
    elif act == "i": await database.change_quantity_by_id(pid, 1)
    elif act == "x": await database.delete_product_by_id(pid)
    await cb.answer("✓")
    await send_list(cb.message.chat.id)

@dp.callback_query(F.data == "r")
async def refresh(cb: types.CallbackQuery):
    await cb.answer("🔄")
    await send_list(cb.message.chat.id)

@dp.callback_query(F.data == "l")
async def low(cb: types.CallbackQuery):
    prods = await database.get_all_products()
    low = [(n,q,u) for _,n,q,u in prods if float(q)<=3]
    txt = "📉 **Мало:**\n" + "\n".join(f"⚠️ `{n}`: {q} {u}" for n,q,u in low) if low else "✅ Всё ок"
    await cb.message.answer(txt, parse_mode="Markdown")
    await cb.answer()

@dp.callback_query(F.data == "i")
async def info(cb: types.CallbackQuery):
    await cb.answer()

async def main():
    await database.init_db()
    print("✅ Запущен!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
