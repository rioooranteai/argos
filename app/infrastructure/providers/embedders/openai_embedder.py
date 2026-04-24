from __future__ import annotations

from app.core.interface.embedder import BaseEmbedder
from langchain_openai import OpenAIEmbeddings

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

    def __init__(self, api_key: str, model: str, chunk_size: int = 1000):
        self.model_name = model

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
            return embeddings
        except Exception as e:
            raise

    def embed_query(self, text: str) -> list[float]:
        try:
            return self._embedder.embed_query(text)
        except Exception as e:
            raise

    @property
    def dimension(self) -> int:
        return _DIMENSIONS.get(self.model_name, 1536)
