from __future__ import annotations

import logging

from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)

DEFAULT_VECTOR_LIMIT = 5

async def vector_node(state: dict, vector_svc: VectorStoreService) -> dict:
    user_input = state["user_input"]

    try:
        raw = vector_svc.search(query=user_input, limit=DEFAULT_VECTOR_LIMIT)

        if not raw:
            logger.info("[vector_node] Ditemukan 0 chunk. - Method 1")
            return {"vector_result": []}

        docs = raw["documents"][0]
        metadatas = raw["metadatas"][0]
        ids = raw["ids"][0]
        distances = raw["distances"][0]

        results = [
            {
                "id": ids[i],
                "text": docs[i],
                "metadata": metadatas[i],
                "distance": distances[i],
            }
            for i in range(len(docs))
        ]

        return {"vector_result": results}

    except Exception as e:
        logger.error(f"[vector_node] Error: {e}")
        return {"vector_result": []}