import sys
import os

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import MessagesState
from pydantic import BaseModel, Field
from typing import Literal
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
from langgraph.prebuilt import ToolNode


from states import ParentState, Analyst_state, make_analyst_work
from langgraph.types import interrupt, Comman
# graph.py
import json
import operator
from typing import List, Annotated
from typing_extensions import TypedDict

# Импорты из LangGraph и LangChain
from langgraph.graph import StateGraph, START, END
from langgraph.constants import Send
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import BaseMessage, SystemMessage, HumanMessage
from tools import multiply, sum_, divide, web_search, search_wikipedia, search_scientific_papers, fetch_web_page_content, search_through_users_pdf
from prompts import FIRST_FILTER_PROMPT, ADDITIONAL_PROMPT, FAST_ANSWER_PROMPT, GENERATE_TOPICS_PROMPT, RESEARCH_TOPICS_PROMPT, FINAL_SUMMARY_PROMPT
from states import ParentState, AnalystState, FirstNode
from config import llm_for_start, llm_topics_human_in_the_loop, llm_reasonings, llm_answers_final_response


tools_all = [multiply, sum_, divide, web_search, search_wikipedia, search_scientific_papers, fetch_web_page_content, search_through_users_pdf]
tools_fast = [multiply, sum_, divide, web_search, search_through_users_pdf]  # обычные функции с @tool или просто callable
tool_node_fast = ToolNode(tools_fast)
tool_node_all = ToolNode(tools_all)



class InputFilterResponse(BaseModel):
    """The scheme for the model-filter's output"""
    reasoning: str 
    pathway: Literal["FAST_TRACK", "DEEP_RESEARCH"]


class SubtopicsClass(BaseModel):
    """The scheme for the subtopics model"""
    subtopics: List[str]


def build_history_context(state: ParentState) -> str:
    """Join an old history with the new one"""
    parts = []
    if state.get("history_summary"):
        parts.append(f"[Composed history of previous diologe:]\n{state['history_summary']}")
    if state.get("history"):
        parts.append("\n".join(state["history"]))
    return "\n\n".join(parts) if parts else "No history context"




def filter_input_node(state: ParentState) -> dict:
    """Evaluate the complexity of the question via FIRST_FILTER_PROMPT."""

    first_analyser_prompt_text = FIRST_FILTER_PROMPT.format(
    topic=state["topic"],
    history=state.get("history", ""),
    is_pdf=state["is_pdf"],
    )

    llm_for_start.with_structured_output(InputFilterResponse)
    verdict = llm_for_start.invoke(
        [SystemMessage(content=first_analyser_prompt_text),
        HumanMessage(content=state["question"]+state.get("topic", ""),),
        SystemMessage(content=ADDITIONAL_PROMPT)
        ])

    return {"reasoning": verdict.reasoning, "pathway": verdict.pathway}


def route_after_filter(state: ParentState) -> Literal["FAST_TRACK", "DEEP_RESEARCH"]:
    """fork path for add_conditional_edges."""
    print(state["reasoning"])
    if state["pathway"] == "FAST_TRACK":
        return "fast_track_node"
    return "generate_subtopics_node"


def fast_track_node(state: ParentState) -> dict:
    """Create a fast answer with the limited number of tools"""
    if not state.get('messages'):# ЗАЧЕМ ТАК И ПОЧЕМУ тАК ВОЗВРАЩАЕМ ОТВЕТ
        prompt_text = FAST_ANSWER_PROMPT.format(
            manner=state.get("format_style", "Normal"),
            history=state.get("history", ""),
            question=state.get("question", ""),
            topic=state.get("topic", ""),
            is_pdf=state["is_pdf"],
        )
        seed = [SystemMessage(content=prompt_text), HumanMessage(content=state["question"])]
        llm_with_tools = llm_for_start.bind_tools(tools_fast)
        result = llm_with_tools.invoke(seed)
        return {"final_report": seed + [result]}
    else:
        llm_with_tools = llm_for_start.bind_tools(tools_fast)
        result = llm_with_tools.invoke(state['masseges'])
        return {"final_report": [result]}


def route_after_fast_track(state: ParentState) -> Literal["tool_node_fast", "extract_final_answer_node"]:
    last_message = state["messages"][-1]
    if getattr(last_message, "tool_calls", None):
        return "tool_node_fast"
    return "extract_final_answer_node"


def extract_final_answer_node(state: ParentState) -> dict:
    return {"final_report": state["messages"][-1].content}


def generate_subtopics_node(state: ParentState) -> dict:
    """Create subtopics for a given topic"""

    topics_prompt_text = GENERATE_TOPICS_PROMPT.format(
            question=state["question"],
            topic=state["topic"],
            
    )
    llm_analyser = llm_topics_human_in_the_loop.with_structured_output(SubtopicsClass)
    verdict = llm_analyser.invoke([SystemMessage(content=topics_prompt_text)])

    return {"subtopics": verdict.subtopics} # Почему так а не DUMP


def human_review_node(state: ParentState) -> dict:
    """Stops the graph and wait for cheking from the user"""
    decision = interrupt({
        "message": "Подтвердите или отредактируйте список подтем для анализа",
        "subtopics": state["subtopics"],
    })
    return {
        "subtopics": decision.get("subtopics", state["subtopics"]),
        "user_approved": decision.get("approved", True),
    }


def route_after_subtopics(state: ParentState) -> List[Send] | str:
    """The second router redirects the execution based on the user's feedback    
    """
    if not state.get('user_approved', True):
        return "generate_subtopics_node"
    else:
        return [
                Send("analyst_node", {
                    "subtopic": st,
                    "parent_topic": state["topic"],
                    "user_id": state["user_id"],
                    "is_pdf": state["is_pdf"],
                })
                for st in state["subtopics"]
            ]

# TODO : Enable multiple times calling
def analyst_node(state: AnalystState):
    """Research for a given subtopic"""
    research_prompt_text = RESEARCH_TOPICS_PROMPT.format(
                question=state["question"],
                topic=state["topic"],
                is_pdf=state["is_pdf"],
        )
    llm_smart_with_tools = llm_reasonings.bind_tools(tool_node_all)
    result = llm_smart_with_tools.invoke([SystemMessage(content=research_prompt_text)])
    return {"final_report_for_subtopic": [result.content]}
 

def final_summary_node(state: ParentState) -> dict:
    prompt_text = FINAL_SUMMARY_PROMPT.format(
        topic=state["topic"],
        question=state["question"],
        reports="\n\n---\n\n".join(state["analyst_reports"]),
    )
    result = llm_answers_final_response.invoke([SystemMessage(content=prompt_text)])
    return {"final_report": result.content}




