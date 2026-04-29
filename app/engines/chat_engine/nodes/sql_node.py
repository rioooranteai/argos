from __future__ import annotations

import logging

from app.services.nl2sql.service import NL2SQLService

logger = logging.getLogger(__name__)


async def sql_node(state: dict, nl2sql_svc: NL2SQLService) -> dict:
    user_input = state["user_input"]
    logger.debug(f"[sql_node] Query: '{user_input}'")

    try:
        result = await nl2sql_svc.process_query(user_input)
        logger.info(f"[sql_node] Status: {result.get('status')} | Rows: {result.get('row_count', 0)}")
        return {"sql_result": result}

    except Exception as e:
        logger.error(f"[sql_node] Error: {e}")
        return {"sql_result": {"status": "error", "message": str(e)}}