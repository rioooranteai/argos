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
    # None = pencarian tidak dijalankan atau GAGAL; [] = berhasil tanpa hasil.
    vector_result: list[dict[str, Any]] | None
    final_answer: str
    # Sumber aktif notebook (dicentang & ready) — membatasi SQL & vector
    active_versions: list[str]
    sources: list[Any]  # list[ActiveSource]
    citations: list[dict[str, Any]]
    # Satu entri per node yang berjalan. Reducer `add` karena sql & vector paralel.
    node_traces: Annotated[list[NodeTrace], operator.add]
