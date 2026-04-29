from __future__ import annotations

import logging

from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)

DEFAULT_VECTOR_LIMIT = 5

async def vector_node(state: dict, vector_svc: VectorStoreService) -> dict:
    user_input = state["user_input"]
    logger.debug(f"[vector_node] Searching: '{user_input}'")

    try:
        raw = vector_svc.search(query=user_input, limit=DEFAULT_VECTOR_LIMIT)

        if isinstance(raw, dict):
            results = raw.get("results", [])
        elif isinstance(raw, list):
            results = raw
        else:
            results = []

        logger.info(f"[vector_node] Ditemukan {len(results)} chunk.")
        return {"vector_result": results}

    except Exception as e:
        logger.error(f"[vector_node] Error: {e}")
        return {"vector_result": []}