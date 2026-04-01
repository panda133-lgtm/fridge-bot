from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from urllib.parse import quote

def get_main_menu():
    """Главное меню внизу экрана"""
    kb = [
        [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_product_keyboard(products):
    """Кнопки для каждого продукта в списке"""
    keyboard = []
    
    for name, qty, unit in products:
        safe_name = quote(name)
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{safe_name}"),
            InlineKeyboardButton(text=name, callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{safe_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{safe_name}")
        ]
        keyboard.append(row)
    
    # Общие кнопки внизу
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh")])
    keyboard.append([InlineKeyboardButton(text="📉 Мало (<3)", callback_data="low_q")])
    keyboard.append([InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_new")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
