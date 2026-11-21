from __future__ import annotations

import logging

from app.core.llm_errors import classify_llm_error
from app.core.observability.telemetry import spans
from app.engines.chat_engine.nodes.timing import Stopwatch
from app.engines.chat_engine.nodes.tracing import traced_node
from app.engines.chat_engine.outcome import NodeTrace
from app.services.nl2sql.service import NL2SQLResult, NL2SQLService

logger = logging.getLogger(__name__)


@traced_node(
    "sql", spans.CHAIN,
    inputs=lambda state: {"question": state["user_input"], "version_ids": state.get("active_versions")},
    outputs=lambda result: {
        "status": result["sql_result"].status,
        "sql": result["sql_result"].sql_query,
        "row_count": result["sql_result"].row_count,
        "truncated": result["sql_result"].truncated,
    },
)
async def sql_node(state: dict, nl2sql_svc: NL2SQLService) -> dict:
    user_input = state["user_input"]
    version_ids = state.get("active_versions") or []
    clock = Stopwatch()

    try:
        result = await nl2sql_svc.process_query(user_input, version_ids)
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
        },
    )
    return {"sql_result": result, "node_traces": [trace]}
