from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from app.infrastructure.interface.embedder import BaseEmbedder

_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


class OpenAIEmbedder(BaseEmbedder):
    """Embedding via LangChain OpenAIEmbeddings, dengan timeout & batas batch eksplisit."""

    def __init__(
        self,
        api_key: str,
        model: str,
        batch_size: int = 100,
        timeout: float = 30,
        max_retries: int = 2,
    ):
        self.model_name = model
        self._embedder = OpenAIEmbeddings(
            api_key=api_key,
            model=model,
            # `chunk_size` di LangChain = jumlah teks per request (batch), bukan token.
            chunk_size=batch_size,
            request_timeout=timeout,
            max_retries=max_retries,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embedder.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embedder.embed_query(text)

    @property
    def dimension(self) -> int:
        return _DIMENSIONS.get(self.model_name, 1536)
