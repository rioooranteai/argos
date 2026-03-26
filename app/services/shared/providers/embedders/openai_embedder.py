from __future__ import annotations

import logging

from langchain_openai import OpenAIEmbeddings

from app.core.config import Config
from app.services.shared.base.embedder import BaseEmbedder

logger = logging.getLogger(__name__)

_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder(BaseEmbedder):
    """
    Embedding provider menggunakan LangChain OpenAIEmbeddings.
    Default model: text-embedding-3-small (cost-efficient).
    """

    def __init__(self):
        self._embedder = OpenAIEmbeddings(
            api_key=Config.OPENAI_API_KEY,
            model=Config.OPENAI_EMBEDDING_MODEL,
            chunk_size=Config.OPENAI_EMBEDDING_CHUNK_SIZE,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            embeddings = self._embedder.embed_documents(texts)
            logger.debug("Embed %d dokumen via LangChain OpenAIEmbeddings", len(texts))
            return embeddings
        except Exception as e:
            logger.error("embed_documents gagal: %s", e)
            raise

    def embed_query(self, text: str) -> list[float]:
        try:
            return self._embedder.embed_query(text)
        except Exception as e:
            logger.error("embed_query gagal: %s", e)
            raise

    @property
    def dimension(self) -> int:
        return _DIMENSIONS.get(Config.OPENAI_EMBEDDING_MODEL, 1536)