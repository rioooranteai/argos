from __future__ import annotations

import logging

from app.core.llm_errors import classify_llm_error
from app.core.observability.telemetry import spans
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import NodeTrace
from app.services.ingestion.profile import DocumentProfile
from app.services.nl2sql.service import NL2SQLResult, NL2SQLService

logger = logging.getLogger(__name__)


def search_question(state: dict) -> str:
    """The router's self-contained rewrite of a follow-up question, else the question itself."""
    return state.get("standalone_question") or state["user_input"]


def _doc_labels(sources: list) -> dict[str, str]:
    """version_id → "type: title" for the CATALOG block of the NL2SQL prompt."""
    labels = {}
    for s in sources or []:
        try:
            p = DocumentProfile.model_validate(s.profile) if s.profile else None
        except ValueError:
            p = None
        labels[s.version_id] = f"{p.document_type}: {p.title}" if p else s.display_name
    return labels


@traced_node(
    "sql", spans.CHAIN,
    inputs=lambda state: {"question": search_question(state), "version_ids": state.get("active_versions")},
    outputs=lambda result: {
        "status": result["sql_result"].status,
        "sql": result["sql_result"].sql_query,
        "row_count": result["sql_result"].row_count,
        "truncated": result["sql_result"].truncated,
        "attempts": result["sql_result"].attempts,
    },
)
async def sql_node(state: dict, nl2sql_svc: NL2SQLService) -> dict:
    question = search_question(state)
    version_ids = state.get("active_versions") or []
    clock = Stopwatch()

    try:
        result = await nl2sql_svc.process_query(
            question, version_ids, _doc_labels(state.get("sources") or [])
        )
    except Exception as e:
        # process_query already returns a typed result; this is only a safety net.
        logger.exception("[sql_node] NL2SQL failed.")
        result = NL2SQLResult(status="error", message=str(e), error_code=classify_llm_error(e))

    logger.info("[sql_node] status=%s rows=%d code=%s", result.status, result.row_count, result.error_code)
    trace = NodeTrace(
        node="sql",
        status=result.status,
        duration_ms=clock.ms(),
        code=result.error_code if result.status == "error" else None,
        details={
            "query": result.sql_query,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "attempts": result.attempts,
        },
    )
    return {"sql_result": result, "node_traces": [trace]}
