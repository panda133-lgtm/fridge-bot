from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from urllib.parse import quote

def get_main_menu():
    kb = [[KeyboardButton(text="📦 Список"), KeyboardButton(text="➕ Добавить")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_product_keyboard(products):
    kb = []
    for name, qty, unit in products:
        safe = quote(name)
        kb.append([
            InlineKeyboardButton(text="➖", callback_data=f"dec_{safe}"),
            InlineKeyboardButton(text=name, callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{safe}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{safe}")
        ])
    kb.append([InlineKeyboardButton(text="🔄", callback_data="refresh")])
    kb.append([InlineKeyboardButton(text="📉 Мало", callback_data="low")])
    kb.append([InlineKeyboardButton(text="➕ Новый", callback_data="add")])
    return InlineKeyboardMarkup(inline_keyboard=kb)
