import os
import tempfile
import asyncio
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from langgraph.types import Command
from src.chunk_pdf import create_vectore_db_for_user
from src import graph_builder
from bot.keyboards import subtopics_confirm_kb

router = Router()
logger = logging.getLogger(__name__)


class EditSubtopics(StatesGroup):
    waiting_for_list = State()


def make_config(user_id: int) -> dict:
    return {"configurable": {"thread_id": str(user_id)}}


uploaded_pdf_users: set[int] = set()


@router.message(F.document)
async def handle_pdf_upload(message: Message):
    if not message.document.file_name.lower().endswith(".pdf"):
        await message.answer("Handle only PDF format!!!!")
        return

    file = await message.bot.get_file(message.document.file_id)
    local_path = os.path.join(tempfile.gettempdir(), f"{message.from_user.id}_{message.document.file_name}")
    await message.bot.download_file(file.file_path, local_path)

    await message.answer("Processing PDF...")
    try:
        await asyncio.to_thread(create_vectore_db_for_user, local_path, str(message.from_user.id))
        uploaded_pdf_users.add(message.from_user.id)
        await message.answer("PDF processed. Document is in memory.")
    except Exception:
        logger.exception("PDF processing failed")
        await message.answer("Did not manage to process PDF")




async def is_waiting_for_resume(user_id: int) -> bool:
    config = make_config(user_id)
    state = await graph_builder.graph.aget_state(config)
    return bool(state.next)



async def run_graph_and_respond(message, payload, config):
    try:
        result = await graph_builder.graph.ainvoke(payload, config=config)
    except Exception:
        logger.exception("Graph execution failed")
        await message.answer("An error occured, try again")
        return

    if "__interrupt__" in result:
        interrupt_data = result["__interrupt__"][0].value
        subtopics_text = "\n".join(f"• {s}" for s in interrupt_data["subtopics"])
        await message.answer(
            f"{interrupt_data['message']}\n\n{subtopics_text}",
            reply_markup=subtopics_confirm_kb(),
        )
        return

    final_text = result.get("final_report") or "Did not manage to make an answer"
    await message.answer(final_text)


@router.message(F.text, ~F.text.startswith("/"))
async def handle_text_message(message: Message, state: FSMContext):
    user_id = message.from_user.id
    config = make_config(user_id)


    fsm_data = await state.get_state()
    if fsm_data == EditSubtopics.waiting_for_list:
        new_subtopics = [line.strip("•- ").strip() for line in message.text.split("\n") if line.strip()]
        await state.clear()
        await run_graph_and_respond(
            message,
            Command(resume={"approved": True, "subtopics": new_subtopics}),
            config,
        )
        return


    if await is_waiting_for_resume(user_id):
        await message.answer(
            "Please use the buttons above to confirm or change the subtopics."
        )
        return


    initial_state = {
        "question": message.text,
        "topic": message.text,
        "user_id": str(user_id),
        "is_pdf": user_id in uploaded_pdf_users,
        "format_style": "Normal",
    }
    await message.answer("Processing request...")
    await run_graph_and_respond(message, initial_state, config)


@router.callback_query(F.data == "subtopics:approve")
async def handle_approve(callback: CallbackQuery):
    user_id = callback.from_user.id
    config = make_config(user_id)
    await callback.message.edit_reply_markup(reply_markup=None) 
    await callback.answer()
    await run_graph_and_respond(
        callback.message,
        Command(resume={"approved": True}),
        config,
    )


@router.callback_query(F.data == "subtopics:edit")
async def handle_edit(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await state.set_state(EditSubtopics.waiting_for_list)
    await callback.message.answer(
        "Please send a new list of subtopics, with each one on a new line."
    )
