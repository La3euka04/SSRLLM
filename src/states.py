import operator
from typing import Annotated, List
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ParentState(TypedDict): # ОБЯСНИТЬ ПОЛЯ
    # входные данные
    question: str
    topic: str
    format_style: str
    user_id: str
    is_pdf: bool

    # вердикт фильтра
    reasoning: str
    pathway: str

    # tool-calling цикл для fast track
    messages: Annotated[List[BaseMessage], add_messages]

    # deep research (map-reduce)
    subtopics: List[str]
    user_approved: bool
    analyst_reports: Annotated[List[str], operator.add]

    # история диалога
    history: List[str]
    history_summary: str
    turn_count: int

    final_report: str


class AnalystState(TypedDict):
    """Изолированный state для одного параллельного воркера (Send)."""
    subtopic: str
    parent_topic: str
    user_id: str
    is_pdf: bool