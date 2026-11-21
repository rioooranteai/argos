from __future__ import annotations

import operator
from typing import Annotated, Any, Literal

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from app.engines.chat_engine.outcome import NodeTrace

RouteDecision = Literal["sql", "vector", "both", "none"]


class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    user_input: str
    route: RouteDecision
    router_reasoning: str
    sql_result: Any  # NL2SQLResult | None
    # None = the search did not run or FAILED; [] = succeeded with no results.
    vector_result: list[dict[str, Any]] | None
    final_answer: str
    # The notebook's active sources (checked & ready) — they scope SQL & vector search
    active_versions: list[str]
    sources: list[Any]  # list[ActiveSource]
    citations: list[dict[str, Any]]
    # One entry per node that ran. Reducer `add` because sql & vector run in parallel.
    node_traces: Annotated[list[NodeTrace], operator.add]
