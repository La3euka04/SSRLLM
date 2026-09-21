from typing import TypedDict
from langgraph.graph import StateGraph, START, END

# 1. Определяем состояние графа
class State(TypedDict):
    value: int


# 2. Определяем узлы (обычные Python-функции)
def add(state: State) -> State:
    return {
        "value": state["value"] + 2,
    }


# 3. Создаём граф
graph = StateGraph(State)

graph.add_node('add', add)

# 5. Соединяем узлы рёбрами
graph.add_edge(START, "add")
graph.add_edge("add", END)

# 6. Компилируем граф
app = graph.compile()


if __name__ == "__main__":
    # 7. Запускаем
    result = app.invoke({"value": 8})

    print(result)


# sk-zWnrquYEDTIUwYkSeSV3Q5x5JT7qltHv