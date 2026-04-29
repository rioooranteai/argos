from __future__ import annotations

from app.core.config import config
from app.infrastructure.interface.embedder import BaseEmbedder
from app.infrastructure.providers.embedders.openai_embedder import OpenAIEmbedder


def get_embedder() -> BaseEmbedder:
    provider = config.EMBEDDING_PROVIDER.lower()

    if provider == "openai":
        return OpenAIEmbedder(
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_EMBEDDING_MODEL,
            chunk_size=config.OPENAI_EMBEDDING_CHUNK_SIZE,
        )

    raise ValueError(f"Unknown embedding provider: '{provider}'")
