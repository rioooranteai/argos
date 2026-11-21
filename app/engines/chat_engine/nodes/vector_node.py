from __future__ import annotations

import asyncio
import logging

from app.core.llm_errors import LLM_ERROR, classify_llm_error
from app.core.telemetry import spans
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import NodeTrace
from app.tools.vector_store.base import BaseVectorStore

logger = logging.getLogger(__name__)

DEFAULT_VECTOR_LIMIT = 5
VECTOR_STORE_FAILED = "VECTOR_STORE_FAILED"


def _hits(result: dict) -> list[dict] | None:
    hits = result.get("vector_result")
    if hits is None:
        return None
    return [
        {"text": h["text"], "version_id": h["metadata"].get("version_id"),
         "page": h["metadata"].get("page_number"), "distance": h["distance"]}
        for h in hits
    ]


@traced_node(
    "vector_search", spans.RETRIEVER,
    inputs=lambda state: {"query": state["user_input"], "version_ids": state.get("active_versions")},
    outputs=_hits,
)
async def vector_node(state: dict, vector_store: BaseVectorStore) -> dict:
    user_input = state["user_input"]
    version_ids = state.get("active_versions")
    clock = Stopwatch()

    try:
        # search() is synchronous (OpenAI embedding HTTP + Chroma query) → run it in a thread.
        hits = await asyncio.to_thread(
            vector_store.search, user_input, version_ids, DEFAULT_VECTOR_LIMIT
        )
    except Exception as e:
        logger.exception("[vector_node] Vector search failed.")
        # Embedding = an OpenAI call (LLM_* codes); anything else is a Chroma failure.
        code = classify_llm_error(e)
        if code == LLM_ERROR:
            code = VECTOR_STORE_FAILED
        # None (not []) so "failed" is not confused with "no results".
        trace = NodeTrace(node="vector", status="error", duration_ms=clock.ms(), code=code)
        return {"vector_result": None, "node_traces": [trace]}

    trace = NodeTrace(
        node="vector",
        status="ok" if hits else "empty",
        duration_ms=clock.ms(),
        details={"hits": len(hits)},
    )
    return {
        "vector_result": [
            {"id": h.id, "text": h.text, "metadata": h.metadata, "distance": h.distance}
            for h in hits
        ],
        "node_traces": [trace],
    }
