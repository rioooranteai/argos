from __future__ import annotations

import asyncio
import logging

from app.services.vector_store.service import VectorStoreService

logger = logging.getLogger(__name__)

DEFAULT_VECTOR_LIMIT = 5


async def vector_node(state: dict, vector_svc: VectorStoreService) -> dict:
    user_input = state["user_input"]
    # Sementara: belum dibatasi ke sumber notebook (langkah 7.3 IMPLEMENTATION_PLAN_AB.md).
    version_ids = state.get("active_versions")

    try:
        # search() sinkron (HTTP embedding OpenAI + query Chroma) → jalankan di thread.
        hits = await asyncio.to_thread(
            vector_svc.search, user_input, version_ids, DEFAULT_VECTOR_LIMIT
        )
        return {
            "vector_result": [
                {"id": h.id, "text": h.text, "metadata": h.metadata, "distance": h.distance}
                for h in hits
            ]
        }
    except Exception:
        logger.exception("[vector_node] Pencarian vector gagal.")
        return {"vector_result": []}
