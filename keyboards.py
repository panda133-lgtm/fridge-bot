from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_menu():
    """Главное меню внизу экрана"""
    kb = [
        [KeyboardButton(text="📦 Список продуктов"), KeyboardButton(text="➕ Добавить продукт")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)
