from __future__ import annotations

from typing import Annotated, Any, Literal
from typing_extensions import TypedDict
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

RouteDecision = Literal["sql", "vector", "both", "none"]

class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    route: RouteDecision
    router_reasoning: str
    sql_result: dict[str, Any] | None
    vector_result: list[dict[str, Any]] | None
    final_answer: str
    error: str | None