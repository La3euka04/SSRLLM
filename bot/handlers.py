import asyncio
import hashlib
import html
import logging
import os
import re
import tempfile

from aiogram import F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command as TgCommand, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from langgraph.types import Command

from src import graph_builder
from src.chunk_pdf import create_vectore_db_for_user, delete_user_pdf, user_has_pdf
from src.limits import DEEP_LIMIT_PER_DAY, deep_left, get_mode, refund_deep_use, set_mode, try_use_deep
from bot import keyboards as kb

router = Router()
logger = logging.getLogger(__name__)

MAX_SUBTOPICS, MAX_SUBTOPIC_LEN = 8, 300
MAX_PDF_BYTES = 20 * 1024 * 1024
SPLIT_LIMIT = 3500

START_TEXT = (
    "👋 <b>Hi! I'm a research assistant.</b>\n\n"
    "<b>What I can do:</b>\n"
    "• Answer simple questions instantly\n"
    "• Break complex questions into subtopics, let you pick the ones you want, "
    "and write a detailed report\n"
    "• Search the web, Wikipedia and arXiv\n"
    "• Answer questions about your PDF files\n\n"
    "<b>How to use me:</b>\n"
    "• Just send a question\n"
    "• Send a PDF (up to 20 MB) - add your question as a caption to get an answer right away\n"
    "• /mode - choose Auto, Fast only or Deep always\n"
    f"• Deep research is limited to {DEEP_LIMIT_PER_DAY} per day, /limit shows what is left\n"
    "• /clear - clear the conversation history and PDFs\n"
    "• /help - show this guide again"
)

MODE_TEXT = (
    "<b>Answer mode</b>\n"
    "• Auto - simple questions get a quick answer, complex ones go to deep research\n"
    "• Fast only - always a quick answer, with a button under it to run deep research on that question\n"
    "• Deep always - every real question goes to deep research (counts toward the daily limit)"
)

CLEAR_TEXT = "Clear conversation history and delete your uploaded PDFs?"


class EditSubtopics(StatesGroup):
    waiting_for_extra = State()


def make_config(uid: int) -> dict:
    return {"configurable": {"thread_id": str(uid)}}


def qhash(q: str) -> str:
    return hashlib.sha1(q.encode()).hexdigest()[:10]


_locks: dict[int, asyncio.Lock] = {}
_bg: set[asyncio.Task] = set()
_last_menu: dict[int, Message] = {}


def get_lock(uid: int) -> asyncio.Lock:
    return _locks.setdefault(uid, asyncio.Lock())


# ── service-message helpers: everything that is not an answer disappears ──

async def safe_delete(msg: Message | None):
    if msg:
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass


def delete_later(msg: Message, delay: float = 5):
    async def run():
        await asyncio.sleep(delay)
        await safe_delete(msg)
    task = asyncio.create_task(run())
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def answer_temp(m: Message, text: str, delay: float = 5, **kw) -> Message:
    sent = await m.answer(text, **kw)
    delete_later(sent, delay)
    return sent


# ── text helpers ──

def md_to_html(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"```(?:\w+)?\n?(.*?)```", r"<pre>\1</pre>", t, flags=re.S)
    t = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", t)
    t = re.sub(r"^\s*[-*]\s+", "• ", t, flags=re.M)
    t = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", t, flags=re.M)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)


def split_text(t: str, limit: int = SPLIT_LIMIT) -> list[str]:
    parts = []
    while len(t) > limit:
        cut = t.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = t.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(t[:cut])
        t = t[cut:].lstrip()
    return parts + ([t] if t else [])


async def send_long(m: Message, text: str, markup=None):
    parts = split_text(text)
    for i, part in enumerate(parts):
        kw = {"reply_markup": markup} if markup and i == len(parts) - 1 else {}
        try:
            await m.answer(md_to_html(part), **kw)
        except TelegramBadRequest:
            await m.answer(part, parse_mode=None, **kw)


def clean_line(s: str) -> str:
    return re.sub(r"^\s*(?:[•\-*]|\d+[.)])\s*", "", s).strip()


def menu_text(subs: list[str], sel: set[int]) -> str:
    items = [f"{'✅' if i in sel else '⬜'} <b>{i + 1}.</b> {html.escape(s)}" for i, s in enumerate(subs)]
    return "Proposed research topics.\nTap a number to toggle a topic:\n\n" + "\n\n".join(items)


def mode_text(mode: str, left: int) -> str:
    return (
        f"{MODE_TEXT}\n\nCurrent mode: <b>{html.escape(kb.MODE_LABELS[mode])}</b>\n"
        f"Deep research left today: {left} of {DEEP_LIMIT_PER_DAY}"
    )


async def send_mode_panel(m: Message, uid: int):
    mode = await asyncio.to_thread(get_mode, uid)
    left = await asyncio.to_thread(deep_left, uid)
    sent = await m.answer(mode_text(mode, left), reply_markup=kb.mode_kb(mode))
    delete_later(sent, 90)


# ── subtopic menu ──

async def show_menu(m: Message, state: FSMContext, subs: list[str]):
    sel = set(range(len(subs)))
    sent = await m.answer(menu_text(subs, sel), reply_markup=kb.subtopics_kb(len(subs), sel))
    await state.update_data(subtopics=subs, selected=sorted(sel), menu_msg_id=sent.message_id)


async def redraw(m: Message, subs: list[str], sel: set[int]):
    try:
        await m.edit_text(menu_text(subs, sel), reply_markup=kb.subtopics_kb(len(subs), sel))
    except TelegramBadRequest:
        pass


async def load_menu(state: FSMContext, uid: int):
    """FSM first; after a bot restart, recover the list from the graph's interrupt."""
    data = await state.get_data()
    if data.get("subtopics"):
        return data["subtopics"], set(data.get("selected", []))
    snap = await graph_builder.graph.aget_state(make_config(uid))
    for task in snap.tasks:
        for itr in task.interrupts:
            subs = itr.value.get("subtopics") if isinstance(itr.value, dict) else None
            if subs:
                await state.update_data(subtopics=subs, selected=list(range(len(subs))))
                return subs, set(range(len(subs)))
    return None, set()


async def drop_stale_menu(bot, chat_id: int, state: FSMContext):
    menu_id = (await state.get_data()).get("menu_msg_id")
    if menu_id:
        try:
            await bot.edit_message_reply_markup(chat_id=chat_id, message_id=menu_id, reply_markup=None)
        except TelegramBadRequest:
            pass
    await state.clear()


# ── graph runner ──

async def run_graph(m: Message, payload, uid: int, state: FSMContext, status: str | None = None) -> bool:
    status_msg, result = None, None
    async with get_lock(uid):
        if status:
            status_msg = await m.answer(status)
        await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
        try:
            result = await graph_builder.graph.ainvoke(payload, config=make_config(uid))
        except Exception:
            logger.exception("Graph execution failed")
        finally:
            await safe_delete(status_msg)
    if result is None:
        await answer_temp(m, "⚠️ Something went wrong, please try again.", 10)
        return False
    if "__interrupt__" in result:
        await show_menu(m, state, result["__interrupt__"][0].value["subtopics"])
        return True

    markup = None
    left = await asyncio.to_thread(deep_left, uid)
    if result.get("pathway") == "FAST_TRACK" and left > 0:
        markup = kb.deep_kb(qhash(result["question"]), left)
    await send_long(m, result.get("final_report") or "Could not generate an answer.", markup)
    if result.get("limit_hit"):
        await answer_temp(
            m,
            f"ℹ️ Deep research limit reached ({DEEP_LIMIT_PER_DAY} per day), "
            "so this was answered in quick mode. The limit resets tomorrow.",
            20,
        )
    return True


async def start_question(m: Message, state: FSMContext, uid: int, text: str, force_deep: bool = False):
    if get_lock(uid).locked():
        await answer_temp(m, "⏳ Previous request is still running, please wait.", 5)
        return
    allowed = await asyncio.to_thread(deep_left, uid) > 0
    if force_deep and not allowed:
        await answer_temp(m, f"Deep research limit reached ({DEEP_LIMIT_PER_DAY} per day). It resets tomorrow.", 6)
        return
    await drop_stale_menu(m.bot, m.chat.id, state)
    mode = await asyncio.to_thread(get_mode, uid)
    payload = {
        "question": text, "topic": text, "user_id": str(uid),
        "is_pdf": await asyncio.to_thread(user_has_pdf, str(uid)),
        "format_style": "Normal",
        "mode": mode,
        "deep_allowed": allowed,
        "force_deep": force_deep,
    }
    await run_graph(m, payload, uid, state, status=f"⏳ Working on it... ({kb.MODE_LABELS[mode]})")


# ── message handlers: ORDER MATTERS, on_text and on_other must stay last ──

@router.message(CommandStart())
@router.message(TgCommand("help"))
async def cmd_start(m: Message, state: FSMContext):
    uid = m.from_user.id
    await safe_delete(m)
    await state.clear()
    await safe_delete(_last_menu.pop(uid, None))
    has_pdf = await asyncio.to_thread(user_has_pdf, str(uid))
    _last_menu[uid] = await m.answer(START_TEXT, reply_markup=kb.main_menu_kb(has_pdf))


@router.message(TgCommand("clear"))
async def cmd_clear(m: Message):
    await safe_delete(m)
    panel = await m.answer(CLEAR_TEXT, reply_markup=kb.confirm_kb("clear:yes"))
    delete_later(panel, 60)


@router.message(TgCommand("mode"))
async def cmd_mode(m: Message):
    await safe_delete(m)
    await send_mode_panel(m, m.from_user.id)


@router.message(TgCommand("limit"))
async def cmd_limit(m: Message):
    await safe_delete(m)
    left = await asyncio.to_thread(deep_left, m.from_user.id)
    await answer_temp(m, f"Deep research left today: {left} of {DEEP_LIMIT_PER_DAY}.", 8)


@router.message(F.document)
async def on_document(m: Message, state: FSMContext):
    doc, uid = m.document, m.from_user.id
    if not (doc.file_name or "").lower().endswith(".pdf"):
        await answer_temp(m, "I only accept PDF files.", 6)
        return
    if doc.file_size and doc.file_size > MAX_PDF_BYTES:
        await answer_temp(m, "File is larger than 20 MB - Telegram doesn't let bots download it.", 8)
        return

    path = os.path.join(tempfile.gettempdir(), f"{uid}_{doc.file_unique_id}.pdf")
    async with get_lock(uid):
        status = await m.answer("📄 Processing PDF...")
        try:
            file = await m.bot.get_file(doc.file_id)
            await m.bot.download_file(file.file_path, path)
            await asyncio.to_thread(create_vectore_db_for_user, path, str(uid))
        except Exception:
            logger.exception("PDF processing failed")
            await status.edit_text("⚠️ Could not process the PDF.")
            delete_later(status, 10)
            return
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    await status.edit_text(f"✅ «{html.escape(doc.file_name)}» added to your knowledge base.")
    delete_later(status, 6)
    caption = (m.caption or "").strip()
    if m.media_group_id:
        await answer_temp(m, "Once all files are uploaded, send your question.", 8)
    elif caption:
        await start_question(m, state, uid, caption)
    else:
        await answer_temp(m, "Now send your question about the document.", 10)


@router.message(EditSubtopics.waiting_for_extra, F.text, ~F.text.startswith("/"))
async def on_extra_topic(m: Message, state: FSMContext):
    subs, sel = await load_menu(state, m.from_user.id)
    prompt_id = (await state.get_data()).get("prompt_msg_id")
    if prompt_id:
        try:
            await m.bot.delete_message(m.chat.id, prompt_id)
        except TelegramBadRequest:
            pass
    if subs is None:
        await state.clear()
        await safe_delete(m)
        await answer_temp(m, "The topic list has expired, please send your question again.", 8)
        return
    room = MAX_SUBTOPICS - len(subs)
    if room <= 0:
        await state.set_state(None)
        await safe_delete(m)
        await answer_temp(m, f"Limit of {MAX_SUBTOPICS} topics reached.", 5)
        return

    extra = [clean_line(s)[:MAX_SUBTOPIC_LEN] for s in m.text.split("\n") if clean_line(s)][:room]
    new = subs + extra
    sel |= set(range(len(subs), len(new)))
    await state.set_state(None)
    await state.update_data(subtopics=new, selected=sorted(sel), prompt_msg_id=None)
    await safe_delete(m)
    try:
        await m.bot.edit_message_text(
            chat_id=m.chat.id, message_id=(await state.get_data()).get("menu_msg_id"),
            text=menu_text(new, sel), reply_markup=kb.subtopics_kb(len(new), sel),
        )
    except (TelegramBadRequest, TypeError):
        await show_menu(m, state, new)
        return
    await answer_temp(m, "Added ✅", 3)


@router.message(F.text, ~F.text.startswith("/"))
async def on_text(m: Message, state: FSMContext):
    await start_question(m, state, m.from_user.id, m.text)


@router.message()
async def on_other(m: Message):
    await answer_temp(m, "I only understand text and PDF files.", 5)


# ── callbacks (order does not matter) ──

@router.callback_query(F.data == "menu:help")
async def cb_help(c: CallbackQuery):
    sent = await c.message.answer(START_TEXT)
    delete_later(sent, 45)
    await c.answer()


@router.callback_query(F.data == "menu:mode")
async def cb_menu_mode(c: CallbackQuery):
    await send_mode_panel(c.message, c.from_user.id)
    await c.answer()


@router.callback_query(F.data.startswith("mode:set:"))
async def cb_mode_set(c: CallbackQuery):
    mode = c.data.split(":")[2]
    if mode not in kb.MODE_LABELS:
        await c.answer()
        return
    uid = c.from_user.id
    await asyncio.to_thread(set_mode, uid, mode)
    left = await asyncio.to_thread(deep_left, uid)
    try:
        await c.message.edit_text(mode_text(mode, left), reply_markup=kb.mode_kb(mode))
    except TelegramBadRequest:
        pass
    await c.answer(f"Mode: {kb.MODE_LABELS[mode]}")
    delete_later(c.message, 5)


@router.callback_query(F.data == "menu:clear")
async def cb_menu_clear(c: CallbackQuery):
    panel = await c.message.answer(CLEAR_TEXT, reply_markup=kb.confirm_kb("clear:yes"))
    delete_later(panel, 60)
    await c.answer()


@router.callback_query(F.data == "menu:delpdf")
async def cb_menu_delpdf(c: CallbackQuery):
    panel = await c.message.answer("Delete all your uploaded PDFs?", reply_markup=kb.confirm_kb("delpdf:yes"))
    delete_later(panel, 60)
    await c.answer()


@router.callback_query(F.data == "confirm:no")
async def cb_confirm_no(c: CallbackQuery):
    await c.message.edit_text("Cancelled.")
    delete_later(c.message, 2)
    await c.answer()


@router.callback_query(F.data == "clear:yes")
async def cb_clear_yes(c: CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    if get_lock(uid).locked():
        await c.answer("Wait for the current request to finish", show_alert=True)
        return
    await drop_stale_menu(c.bot, c.message.chat.id, state)
    try:
        await graph_builder.checkpointer.adelete_thread(str(uid))
        await asyncio.to_thread(delete_user_pdf, str(uid))
        await c.message.edit_text("🧹 History and PDFs cleared.")
    except Exception:
        logger.exception("Failed to clear history")
        await c.message.edit_text("⚠️ Could not clear history.")
    delete_later(c.message, 5)
    await c.answer()


@router.callback_query(F.data == "delpdf:yes")
async def cb_delpdf_yes(c: CallbackQuery):
    if get_lock(c.from_user.id).locked():
        await c.answer("Wait for the current request to finish", show_alert=True)
        return
    await asyncio.to_thread(delete_user_pdf, str(c.from_user.id))
    await c.message.edit_text("🗑 PDFs deleted.")
    delete_later(c.message, 5)
    await c.answer()


@router.callback_query(F.data.startswith("deep:"))
async def cb_deep(c: CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    snap = await graph_builder.graph.aget_state(make_config(uid))
    question = snap.values.get("question")
    if not question or qhash(question) != c.data.split(":")[1]:
        await c.answer("This button is outdated, please ask the question again.", show_alert=True)
        return
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer()
    await start_question(c.message, state, uid, question, force_deep=True)


@router.callback_query(F.data.startswith("st:toggle:"))
async def st_toggle(c: CallbackQuery, state: FSMContext):
    subs, sel = await load_menu(state, c.from_user.id)
    if subs is None:
        await c.answer("List expired, please send your question again", show_alert=True)
        return
    idx = int(c.data.split(":")[2])
    if idx < len(subs):
        sel ^= {idx}
        await state.update_data(selected=sorted(sel))
        await redraw(c.message, subs, sel)
    await c.answer()


@router.callback_query(F.data.in_({"st:all", "st:none"}))
async def st_all_none(c: CallbackQuery, state: FSMContext):
    subs, _ = await load_menu(state, c.from_user.id)
    if subs is None:
        await c.answer("List expired, please send your question again", show_alert=True)
        return
    sel = set(range(len(subs))) if c.data == "st:all" else set()
    await state.update_data(selected=sorted(sel))
    await redraw(c.message, subs, sel)
    await c.answer()


@router.callback_query(F.data == "st:add")
async def st_add(c: CallbackQuery, state: FSMContext):
    subs, _ = await load_menu(state, c.from_user.id)
    if subs is None:
        await c.answer("List expired, please send your question again", show_alert=True)
        return
    if len(subs) >= MAX_SUBTOPICS:
        await c.answer(f"Limit of {MAX_SUBTOPICS} topics", show_alert=True)
        return
    prompt = await c.message.answer("Send your own topic (several allowed, one per line).")
    await state.update_data(menu_msg_id=c.message.message_id, prompt_msg_id=prompt.message_id)
    await state.set_state(EditSubtopics.waiting_for_extra)
    await c.answer()


@router.callback_query(F.data == "st:cancel")
async def st_cancel(c: CallbackQuery, state: FSMContext):
    await state.clear()
    await c.message.edit_text("Research cancelled. Send a new question anytime.")
    delete_later(c.message, 3)
    await c.answer()


@router.callback_query(F.data == "st:go")
async def st_go(c: CallbackQuery, state: FSMContext):
    uid = c.from_user.id
    if get_lock(uid).locked():
        await c.answer("Already running, please wait", show_alert=True)
        return
    subs, sel = await load_menu(state, uid)
    if subs is None:
        await c.answer("List expired, please send your question again", show_alert=True)
        return
    if not sel:
        await c.answer("Select at least one topic", show_alert=True)
        return

    left = await asyncio.to_thread(try_use_deep, uid)
    if left is None:
        await state.clear()
        await c.message.edit_text(
            f"Deep research limit reached ({DEEP_LIMIT_PER_DAY} per day). It resets tomorrow.", reply_markup=None
        )
        delete_later(c.message, 6)
        await c.answer()
        return

    chosen = [subs[i] for i in sorted(sel) if i < len(subs)]
    await state.clear()
    await c.message.edit_text(
        "🚀 Starting research on:\n\n" + "\n".join(f"• {html.escape(s)}" for s in chosen)
        + f"\n\nDeep research left today: {left}",
        reply_markup=None,
    )
    await c.answer()
    ok = await run_graph(c.message, Command(resume={"approved": True, "subtopics": chosen}), uid, state)
    if not ok:
        await asyncio.to_thread(refund_deep_use, uid)
    await safe_delete(c.message)
