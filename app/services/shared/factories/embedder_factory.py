from __future__ import annotations

import logging

from app.core.config import Config
from app.services.shared.base.embedder import BaseEmbedder

logger = logging.getLogger(__name__)

def get_embedder() -> BaseEmbedder:
    provider = Config.EMBEDDING_PROVIDER.lower()

    if provider == "openai":
        from app.services.shared.providers.embedders.openai_embedder import OpenAIEmbedder
        logger.info("Embedder: OpenAI (%s)", Config.OPENAI_EMBEDDING_MODEL)
        return OpenAIEmbedder(
            api_key=Config.OPENAI_API_KEY,
            model=Config.OPENAI_EMBEDDING_MODEL,
            chunk_size=Config.OPENAI_EMBEDDING_CHUNK_SIZE,
        )

    raise ValueError(f"Unknown embedding provider: '{provider}'")