from typing import Annotated, List
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

RESET = "__RESET__"

def reports_reducer(left, right):
    if right == [RESET]:
        return []
    return (left or []) + right

class ParentState(TypedDict):
    question: str
    topic: str
    user_id: str
    is_pdf: bool
    format_style: str
    reasoning: str
    pathway: str
    messages: Annotated[List[BaseMessage], add_messages]
    subtopics: List[str]
    user_approved: bool
    analyst_reports: Annotated[List[str], reports_reducer]
    final_report: str
    history: List[str]
    history_summary: List[str]
    turn_count: int
    turn_summary_count: int     
    deep_allowed: bool
    limit_hit: bool
    force_deep: bool
    mode: str

class AnalystState(TypedDict):
    subtopic: str
    question: str
    user_id: str
    is_pdf: bool
    messages: Annotated[List[BaseMessage], add_messages]
    steps: int
    report: str