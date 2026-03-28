from __future__ import annotations

import logging

from langchain_openai import OpenAIEmbeddings

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
    Menerima parameter langsung dari Factory untuk memudahkan Dependency Injection.
    """

    # KUNCI PERBAIKAN: Buka "pintu" agar class ini bisa menerima argumen dari Factory
    def __init__(self, api_key: str, model: str, chunk_size: int = 1000):
        self.model_name = model  # Simpan nama model untuk properti dimension nanti

        # Teruskan argumen ke library bawaan LangChain
        self._embedder = OpenAIEmbeddings(
            api_key=api_key,
            model=model,
            chunk_size=chunk_size,
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
        # Gunakan self.model_name yang sudah disimpan saat init
        return _DIMENSIONS.get(self.model_name, 1536)