from __future__ import annotations

from app.core.config import app_config, secrets
from app.infrastructure.interface.embedder import BaseEmbedder
from app.infrastructure.providers.embedders.openai_embedder import OpenAIEmbedder


def get_embedder() -> BaseEmbedder:
    provider = app_config.EMBEDDING_PROVIDER.lower()

    if provider == "openai":
        return OpenAIEmbedder(
            api_key=secrets.OPENAI_API_KEY,
            model=app_config.OPENAI_EMBEDDING_MODEL,
            batch_size=app_config.EMBED_BATCH_SIZE,
            timeout=app_config.EMBED_TIMEOUT,
        )

    raise ValueError(f"Unknown embedding provider: '{provider}'")
