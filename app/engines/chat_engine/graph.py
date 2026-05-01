from __future__ import annotations

import logging
from functools import partial
from typing import Any

from app.engines.chat_engine.nodes.router import router_node
from app.engines.chat_engine.nodes.sql_node import sql_node
from app.engines.chat_engine.nodes.synthesizer import synthesizer_node
from app.engines.chat_engine.nodes.vector_node import vector_node
from app.engines.chat_engine.state import ChatState, RouteDecision
from app.infrastructure.interface.llm import BaseLLM
from app.services.nl2sql.service import NL2SQLService
from app.services.vector_store.service import VectorStoreService
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

logger = logging.getLogger(__name__)


async def _synthesizer_wrapper(state: dict, llm: BaseLLM) -> dict:
    result = await synthesizer_node(state, llm=llm)

    return {
        **result,
        "messages": [AIMessage(content=result['final_answer'])],
    }


def _route_condition(state: ChatState) -> list[str]:
    """
    Conditional edge: tentukan node berikutnya berdasarkan keputusan router.
    LangGraph akan menjalankan semua node dalam list secara paralel.
    """
    route: RouteDecision = state['route']

    if route == "sql":
        return ["sql_node"]
    elif route == "vector":
        return ["vector_node"]
    elif route == "both":
        return ["sql_node", "vector_node"]  # dijalankan paralel
    else:
        # route == "none" → langsung ke synthesizer (akan jawab "tidak ada data")
        return ["synthesizer_node"]


def build_graph(
        llm: BaseLLM,
        nl2sql_svc: NL2SQLService,
        vector_svc: VectorStoreService,
) -> Any:
    """
    Build dan compile LangGraph StateGraph untuk ChatEngine.

    Dependency di-inject via functools.partial sehingga node
    tetap callable dengan signature (state) -> dict.
    """
    builder = StateGraph(ChatState)

    # --- Daftarkan semua node ---
    builder.add_node("router_node", partial(router_node, llm=llm))
    builder.add_node("sql_node", partial(sql_node, nl2sql_svc=nl2sql_svc))
    builder.add_node("vector_node", partial(vector_node, vector_svc=vector_svc))
    builder.add_node("synthesizer_node", partial(_synthesizer_wrapper, llm=llm))

    # --- Definisikan edges ---
    # START → router
    builder.add_edge(START, "router_node")

    # router → (sql | vector | both | synthesizer) via conditional
    builder.add_conditional_edges(
        "router_node",
        _route_condition,
        {
            "sql_node": "sql_node",
            "vector_node": "vector_node",
            "synthesizer_node": "synthesizer_node",
        },
    )

    # sql & vector → synthesizer (setelah keduanya selesai, jika paralel)
    builder.add_edge("sql_node", "synthesizer_node")
    builder.add_edge("vector_node", "synthesizer_node")

    # synthesizer → END
    builder.add_edge("synthesizer_node", END)

    compiled = builder.compile()
    logger.info("ChatEngine graph berhasil di-compile.")
    return compiled
