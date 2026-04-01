from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from urllib.parse import quote

def get_main_menu():
    kb = [
        [KeyboardButton(text="📦 Список продуктов")],
        [KeyboardButton(text="➕ Добавить вручную")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_product_list_keyboard(products):
    keyboard = []
    
    for name, qty in products:
        status = "⚠️" if qty <= 3 else "✅"
        encoded_name = quote(name)
        
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
            InlineKeyboardButton(text=f"{status} {name} ({qty})", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
