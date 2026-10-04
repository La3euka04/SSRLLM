from aiogram.types import InlineKeyboardButton as Btn, InlineKeyboardMarkup as Markup
from aiogram.utils.keyboard import InlineKeyboardBuilder

MODE_LABELS = {"auto": "🤖 Auto", "fast": "⚡ Fast only", "deep": "🔬 Deep always"}


def main_menu_kb(has_pdf: bool) -> Markup:
    b = InlineKeyboardBuilder()
    b.button(text="📖 How to use", callback_data="menu:help")
    b.button(text="⚙️ Answer mode", callback_data="menu:mode")
    b.button(text="🧹 Clear history", callback_data="menu:clear")
    if has_pdf:
        b.button(text="🗑 Delete my PDFs", callback_data="menu:delpdf")
    b.adjust(1)
    return b.as_markup()


def mode_kb(current: str) -> Markup:
    return Markup(inline_keyboard=[
        [Btn(text=("✅ " if key == current else "") + label, callback_data=f"mode:set:{key}")]
        for key, label in MODE_LABELS.items()
    ])


def confirm_kb(yes_data: str) -> Markup:
    return Markup(inline_keyboard=[[
        Btn(text="✅ Yes", callback_data=yes_data),
        Btn(text="↩️ No", callback_data="confirm:no"),
    ]])


def deep_kb(qhash: str, left: int) -> Markup:
    return Markup(inline_keyboard=[[
        Btn(text=f"🔬 Deep research on this ({left} left today)", callback_data=f"deep:{qhash}")
    ]])


def subtopics_kb(n: int, selected: set[int]) -> Markup:
    nums = [Btn(text=f"{'✅' if i in selected else '⬜'} {i + 1}", callback_data=f"st:toggle:{i}") for i in range(n)]
    rows = [nums[i:i + 4] for i in range(0, n, 4)]
    rows += [
        [Btn(text="☑️ Select all", callback_data="st:all"), Btn(text="🚫 Clear all", callback_data="st:none")],
        [Btn(text="➕ Add my own", callback_data="st:add")],
        [Btn(text=f"🚀 Start research ({len(selected)})", callback_data="st:go")],
        [Btn(text="✖️ Cancel", callback_data="st:cancel")],
    ]
    return Markup(inline_keyboard=rows)
