import sys
import os

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import MessagesState

sys.path.append(root_dir)
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from src.settings import settings
from typing_extensions import TypedDict
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage
from typing import Annotated
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from config import llm_for_star, llm_topics_human_in_the_loop, llm_reasonings, llm_answers_final_response
from chunk_pdf import create_vectore_db_for_user
from tools import multiply, sum_, divide, web_search, search_wikipedia, search_scientific_papers, fetch_web_page_content, search_through_users_pdf
from states import ParentState, Analyst_state, make_analyst_work


