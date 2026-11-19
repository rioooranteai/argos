from __future__ import annotations

import logging

from app.services.nl2sql.service import NL2SQLResult, NL2SQLService

logger = logging.getLogger(__name__)


async def sql_node(state: dict, nl2sql_svc: NL2SQLService) -> dict:
    user_input = state["user_input"]
    version_ids = state.get("active_versions") or []

    try:
        result = await nl2sql_svc.process_query(user_input, version_ids)
        logger.info("[sql_node] status=%s rows=%d", result.status, result.row_count)
        return {"sql_result": result}
    except Exception as e:
        logger.exception("[sql_node] NL2SQL gagal.")
        return {"sql_result": NL2SQLResult(status="error", message=str(e))}
