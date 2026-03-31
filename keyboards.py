from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup
from urllib.parse import quote

def get_main_menu():
    """Главное меню внизу экрана"""
    kb = [
        [KeyboardButton(text="📦 Список продуктов")],
        [KeyboardButton(text="➕ Добавить вручную")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_product_list_keyboard(products):
    """
    Генерирует кнопки для каждого продукта в списке.
    Для каждого продукта: [ -1 ] [ Название (кол-во) ] [ +1 ] [ Удалить ]
    """
    keyboard = []
    
    for name, qty in products:
        # Определяем статус (мало или нормально)
        status = "⚠️" if qty < 3 else "✅"
        
        # Кодируем название для callback_data (чтобы пробелы и символы не ломали)
        encoded_name = quote(name)
        
        row = [
            InlineKeyboardButton(text="➖", callback_data=f"dec_{encoded_name}"),
            InlineKeyboardButton(text=f"{status} {name} ({qty})", callback_data="info"),
            InlineKeyboardButton(text="➕", callback_data=f"inc_{encoded_name}"),
            InlineKeyboardButton(text="🗑", callback_data=f"del_{encoded_name}")
        ]
        keyboard.append(row)
    
    # Кнопка обновления списка
    keyboard.append([InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)
