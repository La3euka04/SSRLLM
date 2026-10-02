from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup


def subtopics_confirm_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="subtopics:approve")
    builder.button(text="✏️ Изменить", callback_data="subtopics:edit")
    builder.adjust(2)
    return builder.as_markup()
