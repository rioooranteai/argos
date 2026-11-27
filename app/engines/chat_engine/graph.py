from __future__ import annotations

import logging
from functools import partial
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.engines.chat_engine.nodes.history import router_history_node, synth_history_node
from app.engines.chat_engine.nodes.router import router_node
from app.engines.chat_engine.nodes.sql_node import sql_node
from app.engines.chat_engine.nodes.synthesizer import synthesizer_node
from app.engines.chat_engine.nodes.vector_node import vector_node
from app.engines.chat_engine.state import ChatState, RouteDecision
from app.services.nl2sql.service import NL2SQLService
from app.tools.llm.base import BaseLLM
from app.tools.vector_store.base import BaseVectorStore

logger = logging.getLogger(__name__)


async def _synthesizer_wrapper(state: dict, llm: BaseLLM) -> dict:
    result = await synthesizer_node(state, llm=llm)

    return {
        **result,
        "messages": [AIMessage(content=result['final_answer'])],
    }


def _route_condition(state: ChatState) -> list[str]:
    """
    Conditional edge: pick the next node(s) from the router's decision.
    LangGraph runs every node in the list in parallel.
    """
    route: RouteDecision = state['route']

    if route == "sql":
        return ["sql_node"]
    elif route == "vector":
        return ["vector_node"]
    elif route == "both":
        return ["sql_node", "vector_node"]  # run in parallel
    else:
        # route == "none" → straight to the synthesizer (it will answer "no data")
        return ["synth_history_node"]


def _after_sql(state: ChatState) -> str:
    """Route `sql` came back with no rows → also search the documents before answering.

    The structured columns only hold name/brand/price/pros/cons, so an attribute such as
    "7 seats" may only be found in the document text. With route `both` the vector search
    already ran in parallel, so this only applies to `sql` alone. A failed SQL query is not
    retried through this path (the synthesizer reports the failure).
    """
    sql_result = state.get("sql_result")
    if state.get("route") == "sql" and sql_result is not None and sql_result.status == "empty":
        logger.info("[graph] SQL returned no rows; falling back to document search.")
        return "vector_node"
    return "synth_history_node"


def build_graph(
        llm: BaseLLM,
        nl2sql_svc: NL2SQLService,
        vector_store: BaseVectorStore,
        router_llm: BaseLLM | None = None,
) -> Any:
    """
    Build and compile the LangGraph StateGraph for ChatEngine.

    Dependencies are injected via functools.partial so each node
    stays callable with the signature (state) -> dict.
    """
    builder = StateGraph(ChatState)

    # --- Register every node ---
    # Each LLM node gets its own cut of the history (`messages` stays whole).
    builder.add_node("router_history_node", router_history_node)
    builder.add_node("synth_history_node", synth_history_node)
    # A small model is enough for the router (classification); the synthesizer uses the chat model.
    builder.add_node("router_node", partial(router_node, llm=router_llm or llm))
    builder.add_node("sql_node", partial(sql_node, nl2sql_svc=nl2sql_svc))
    builder.add_node("vector_node", partial(vector_node, vector_store=vector_store))
    builder.add_node("synthesizer_node", partial(_synthesizer_wrapper, llm=llm))

    # --- Define the edges ---
    # START → router history → router
    builder.add_edge(START, "router_history_node")
    builder.add_edge("router_history_node", "router_node")

    # router → (sql | vector | both | synthesizer) via conditional
    builder.add_conditional_edges(
        "router_node",
        _route_condition,
        {
            "sql_node": "sql_node",
            "vector_node": "vector_node",
            "synth_history_node": "synth_history_node",
        },
    )

    # sql → synthesizer, or → vector first when route `sql` found no rows (fallback).
    # With route `both`, sql & vector run in the same step, so the synthesizer runs once.
    builder.add_conditional_edges(
        "sql_node",
        _after_sql,
        {"vector_node": "vector_node", "synth_history_node": "synth_history_node"},
    )
    builder.add_edge("vector_node", "synth_history_node")

    # synth history → synthesizer → END (sql & vector both lead here, so it runs once)
    builder.add_edge("synth_history_node", "synthesizer_node")
    builder.add_edge("synthesizer_node", END)

    compiled = builder.compile()

    return compiled
