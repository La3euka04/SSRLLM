from typing import List, Annotated
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.constants import Send
import operator

# 1. Определяем состояние графа
class ParentState(TypedDict):
    topic: str
    format_style: str
    user_id: str

    subtopics: List[str]
    user_approved: bool # for Human in the loop

    analyst_report:Annotated[List[str], operator.add] 

    final_report: str


class Analyst_state(TypedDict):
    subtopic: str            # Конкретная подтема (например, "Технологии батарей")
    user_id: str             # Прокидывается из родителя, чтобы работал тул поиска по PDF


    messages: List[BaseMessage] 

    subtopic_report: str     # Финальный черновик статьи по этой конкретной подтеме

def make_analyst_work(state: ParentState):

    if not state.get('user_approved'):
        return "wait_for_user_node"

    return [Send('analysis_node', {"subtopic": topic, "user_id": state['user_id'], 'messages': [] }
                )
                for topic in state['subtopics']]
