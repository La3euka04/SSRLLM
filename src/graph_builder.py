import sys
import os

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.append(root_dir)
from typing import List, Literal
from pydantic import BaseModel

from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Send, interrupt
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, RemoveMessage

from .tools import (multiply, sum_, divide, web_search, search_wikipedia,
                   search_scientific_papers, fetch_web_page_content, search_through_users_pdf)
from .prompts import (FIRST_FILTER_PROMPT, DIRECT_ANSWER_PROMPT, ADDITIONAL_PROMPT, FAST_ANSWER_PROMPT,
                     GENERATE_TOPICS_PROMPT, RESEARCH_TOPICS_PROMPT, FINAL_SUMMARY_PROMPT,
                     HISTORY_SUMMARY_PROMPT_1, HISTORY_SUMMARY_SUMMARY_PROMPT_1, HISTORY_SUMMARY_PROMPT_2, MAX_TOOL_STEPS_FAST, MAX_TOOL_STEPS)
from .states import ParentState, AnalystState, RESET
from .config import (llm_for_start, llm_topics_human_in_the_loop,
                    llm_reasonings, llm_answers_final_response)
from pathlib import Path
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel, Field


tools_all = [multiply, sum_, divide, web_search, search_wikipedia, search_scientific_papers, fetch_web_page_content, search_through_users_pdf]
tools_fast = [multiply, sum_, divide, web_search, search_through_users_pdf]  # обычные функции с @tool или просто callable
tool_node_fast = ToolNode(tools_fast, handle_tool_errors=True)
tool_node_all = ToolNode(tools_all, handle_tool_errors=True)

# DB_DIR = Path(r"C:/Projects/LLM_AGENTS_COURSE/src/SPWS/src/db")


DB_PATH = Path(__file__).resolve().parent.parent / "DB" / "checkpoints.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_checkpointer_cm = AsyncSqliteSaver.from_conn_string(str(DB_PATH))
checkpointer = None
graph = None


async def init_graph():
    global checkpointer, graph
    checkpointer = await _checkpointer_cm.__aenter__()
    graph = builder.compile(checkpointer=checkpointer)
    return graph


async def close_graph():
    await _checkpointer_cm.__aexit__(None, None, None)



class InputFilterResponse(BaseModel):
    reasoning: str
    pathway: Literal["DIRECT", "FAST_TRACK", "DEEP_RESEARCH"]


class SubtopicsClass(BaseModel):
    """Short titles of research subtopics."""
    subtopics: List[str] = Field(
        description="3-5 short titles, 2-7 words each, no explanations"
    )


def build_history_context(state: ParentState) -> str:
    """Join an old history with the new one"""
    parts = []
    if state.get("history_summary"):
        parts.append("[Summary of earlier dialogue]\n" + "\n\n".join(state["history_summary"]))
    if state.get("history"):
        parts.append("[Recent turns]\n" + "\n\n".join(state["history"]))
    return "\n\n".join(parts) if parts else "No history context"


def filter_input_node(state: ParentState) -> dict:
    """Evaluate the complexity of the question via FIRST_FILTER_PROMPT"""

    if state.get("force_deep") and state.get("deep_allowed", True):
        return {"reasoning": "Deep research requested by the user", "pathway": "DEEP_RESEARCH", "limit_hit": False}

    first_analyser_prompt_text = FIRST_FILTER_PROMPT.format(
    topic=state["topic"],
    history=build_history_context(state),
    is_pdf=state["is_pdf"],
    )

    llm_for_start_structured = llm_for_start.with_structured_output(InputFilterResponse)
    verdict = llm_for_start_structured.invoke(
        [SystemMessage(content=first_analyser_prompt_text),
        HumanMessage(content=state["question"]+state.get("topic", ""),),
        SystemMessage(content=ADDITIONAL_PROMPT)
        ])

    mode = state.get("mode", "auto")
    pathway, limit_hit = verdict.pathway, False
    if mode == "deep" and pathway == "FAST_TRACK":
        pathway = "DEEP_RESEARCH"
    if pathway == "DEEP_RESEARCH":
        if mode == "fast":
            pathway = "FAST_TRACK"
        elif not state.get("deep_allowed", True):
            pathway, limit_hit = "FAST_TRACK", True
    return {"reasoning": verdict.reasoning, "pathway": pathway, "limit_hit": limit_hit}


def route_after_filter(state: ParentState) -> Literal["direct_answer_node", "fast_track_node", "generate_subtopics_node"]:
    return {
        "DIRECT": "direct_answer_node",
        "FAST_TRACK": "fast_track_node",
    }.get(state["pathway"], "generate_subtopics_node")



def direct_answer_node(state: ParentState) -> dict:
    """Answers imidiently without tools"""
    prompt = DIRECT_ANSWER_PROMPT.format(history=build_history_context(state))
    result = llm_for_start.invoke([SystemMessage(content=prompt), HumanMessage(content=state["question"])])
    return {"final_report": result.content}


def fast_track_node(state: ParentState) -> dict:
    """Create a fast answer with the limited number of tools"""
    if not state.get('messages'):
        prompt_text = FAST_ANSWER_PROMPT.format(
            manner=state.get("format_style", "Normal"),
            history=build_history_context(state),
            question=state.get("question", ""),
            is_pdf=state["is_pdf"],
        )
        seed = [SystemMessage(content=prompt_text), HumanMessage(content=state["question"])]
        llm_with_tools = llm_for_start.bind_tools(tools_fast)
        result = llm_with_tools.invoke(seed)
        return {"messages": seed + [result]}
    else:
        llm_with_tools = llm_for_start.bind_tools(tools_fast)
        result = llm_with_tools.invoke(state['messages'])
        return {"messages": [result]}


def route_after_fast_track(state: ParentState) -> Literal["tool_node_fast", "extract_final_answer_node"]:
    """Fork node for fast track with tools"""
    last = state["messages"][-1]
    ai_steps = sum(isinstance(m, AIMessage) for m in state["messages"])
    if getattr(last, "tool_calls", None) and ai_steps <= MAX_TOOL_STEPS_FAST:
        return "tool_node_fast"
    return "extract_final_answer_node"


def extract_final_answer_node(state: ParentState) -> dict:
    """Gives the final report avoiding tool calling"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None): 
        last = llm_for_start.invoke(
            state["messages"][:-1] + [HumanMessage(content="Give the final answer now, without using more tools")]
        )
    return {"final_report": last.content}


def generate_subtopics_node(state: ParentState) -> dict:
    """Create subtopics for a given topic"""

    topics_prompt_text = GENERATE_TOPICS_PROMPT.format(
            question=state["question"],
            topic=state["topic"],
            
    )
    llm_analyser = llm_topics_human_in_the_loop.with_structured_output(SubtopicsClass)
    verdict = llm_analyser.invoke([SystemMessage(content=topics_prompt_text)])
    subtopics = [s.strip()[:80] for s in verdict.subtopics[:5]]
    return {"subtopics": subtopics}


def human_review_node(state: ParentState) -> dict:
    """Stops the graph and wait for cheking from the user"""
    decision = interrupt({
        "message": "Approve or change the subtopics for analysis:",
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
                    "question": state["question"], 
                    "user_id": state["user_id"],
                    "is_pdf": state["is_pdf"],
                })
                for st in state["subtopics"]
            ]

def analyst_agent(state: AnalystState):
    """Research for a given subtopic"""
    llm = llm_reasonings.bind_tools(tools_all)
    if not state.get('messages'):
        research_prompt_text = RESEARCH_TOPICS_PROMPT.format(
                        topic=state["subtopic"],
                        is_pdf=state["is_pdf"],
                )
        
        seed = [SystemMessage(content=research_prompt_text), HumanMessage(content=state["subtopic"])]
        return {"messages": seed + [llm.invoke(seed)], "steps": 1}
    return {"messages": [llm.invoke(state["messages"])], "steps": state["steps"] + 1}


def route_after_analyst_agent(state: AnalystState) -> Literal["analyst_tools", "analyst_finish"]:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None) and state["steps"] < MAX_TOOL_STEPS:
        return "analyst_tools"
    return "analyst_finish"
 

def final_summary_node(state: ParentState) -> dict:
    prompt_text = FINAL_SUMMARY_PROMPT.format(
        topic=state["topic"],
        question=state["question"],
        reports="\n\n---\n\n".join(state["analyst_reports"]),
    )
    result = llm_answers_final_response.invoke([SystemMessage(content=prompt_text)])
    return {"final_report": result.content}


def update_history_node(state: ParentState) -> dict:
    """Custom history summary"""
    new_turn = f"Q: {state['question']}\nA: {state['final_report']}"
    history = state.get("history", []) + [new_turn]
    history_summary = list(state.get("history_summary", []))   
    turn_count = state.get("turn_count", 0) + 1
    turn_summary_count = state.get("turn_summary_count", 0) + 1

    if turn_count % 4 == 0:
        if turn_summary_count % 3 == 0:

            summary_prompt = HISTORY_SUMMARY_PROMPT_1.format(
                recent_turns="\n\n".join(history),
            )
            summary_result = llm_for_start.invoke([SystemMessage(content=summary_prompt)])
            history_summary += [summary_result.content]

            history_summary_prompt = HISTORY_SUMMARY_SUMMARY_PROMPT_1.format(
                previous_summaries="\n\n".join(history_summary),
            )
            history_summary_result = llm_for_start.invoke([SystemMessage(content=history_summary_prompt)])

            return {
                "history": [],                                         
                "history_summary": [history_summary_result.content],    
                "turn_summary_count": 0,                               
                "turn_count": 0,                                        
            }

        else:
            summary_prompt = HISTORY_SUMMARY_PROMPT_2.format(
                previous_summary="\n\n".join(history_summary[-1:]) or "(not yet)", 
                recent_turns="\n\n".join(history),
            )
            summary_result = llm_for_start.invoke([SystemMessage(content=summary_prompt)])
            history_summary += [summary_result.content]
            return {
                "history": [],              
                "history_summary": history_summary,
                "turn_count": 0,            
                "turn_summary_count": turn_summary_count,
            }

    else:
        return {
            "history": history,
            "turn_count": turn_count,
        }


def reset_turn_node(state: ParentState) -> dict:
    """Clean the information that should not be past """
    return {
        "messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES)],
        "analyst_reports": [RESET],      
        "subtopics": [],
        "user_approved": True,
        "final_report": "",
    }

def analyst_finish(state: AnalystState) -> dict:
    """Gives the final report avoiding tool calling"""
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        last = llm_reasonings.invoke(
            state["messages"][:-1] + [HumanMessage(content="Write the final report now, without using more tools.")]
        )
    return {"report": last.content}

#-----------------------------------#
#-------GRAPH BUILDER---------------#
#-----------------------------------#


analyst_builder = StateGraph(AnalystState)
analyst_builder.add_node("analyst_agent", analyst_agent)
analyst_builder.add_node("analyst_tools", tool_node_all)
analyst_builder.add_node("analyst_finish", analyst_finish)
analyst_builder.add_edge(START, "analyst_agent")
analyst_builder.add_conditional_edges(
    "analyst_agent", route_after_analyst_agent,
    {"analyst_tools": "analyst_tools", "analyst_finish": "analyst_finish"},
)
analyst_builder.add_edge("analyst_tools", "analyst_agent")
analyst_builder.add_edge("analyst_finish", END)
analyst_graph = analyst_builder.compile()


def analyst_node(state: AnalystState) -> dict:
    out = analyst_graph.invoke(state)
    return {"analyst_reports": [out["report"]]}


builder = StateGraph(ParentState)

builder.add_node("reset_turn_node", reset_turn_node)
builder.add_node("filter_input_node", filter_input_node)

# fast track
builder.add_node("fast_track_node", fast_track_node)
builder.add_node("tool_node_fast", tool_node_fast)
builder.add_node("extract_final_answer_node", extract_final_answer_node)

# deep research
builder.add_node("generate_subtopics_node", generate_subtopics_node)
builder.add_node("human_review_node", human_review_node)
builder.add_node("analyst_node", analyst_node)
builder.add_node("final_summary_node", final_summary_node)
builder.add_node("direct_answer_node", direct_answer_node)
builder.add_node("update_history_node", update_history_node)


builder.add_edge(START, "reset_turn_node")
builder.add_edge("reset_turn_node", "filter_input_node")

builder.add_conditional_edges(
    "filter_input_node", route_after_filter,
    {"direct_answer_node": "direct_answer_node",
     "fast_track_node": "fast_track_node",
     "generate_subtopics_node": "generate_subtopics_node"},
)
builder.add_edge("direct_answer_node", "update_history_node")


builder.add_conditional_edges(
    "fast_track_node", route_after_fast_track,
    {"tool_node_fast": "tool_node_fast",
     "extract_final_answer_node": "extract_final_answer_node"},
)
builder.add_edge("tool_node_fast", "fast_track_node")
builder.add_edge("extract_final_answer_node", "update_history_node")


builder.add_edge("generate_subtopics_node", "human_review_node")
builder.add_conditional_edges(
    "human_review_node", route_after_subtopics,
    ["generate_subtopics_node", "analyst_node"],   # Send-роутер: перечисляем возможные цели списком
)
builder.add_edge("analyst_node", "final_summary_node")
builder.add_edge("final_summary_node", "update_history_node")

builder.add_edge("update_history_node", END)

