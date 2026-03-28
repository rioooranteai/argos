from __future__ import annotations
from app.core.config import Config
from app.services.shared.base.embedder import BaseEmbedder


def get_embedder() -> BaseEmbedder:
    provider = Config.EMBEDDING_PROVIDER.lower()

    if provider == "openai":
        from app.services.shared.providers.embedders.openai_embedder import OpenAIEmbedder
        return OpenAIEmbedder(
            api_key=Config.OPENAI_API_KEY,
            model=Config.OPENAI_EMBEDDING_MODEL,
            chunk_size=Config.OPENAI_EMBEDDING_CHUNK_SIZE,
        )

    raise ValueError(f"Unknown embedding provider: '{provider}'")