from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from app.core.observability.ai_calls.recorder import recorder
from app.tools.embedding.base import BaseEmbedder


class OpenAIEmbedder(BaseEmbedder):
    """Embeddings via LangChain OpenAIEmbeddings, with an explicit timeout & batch limit."""

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
            # `chunk_size` in LangChain = texts per request (batch), not tokens.
            chunk_size=batch_size,
            request_timeout=timeout,
            max_retries=max_retries,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        # LangChain does not return embedding token usage → the token columns are NULL.
        with recorder.track("embedding", self.model_name) as call:
            call.content(input=texts)
            return self._embedder.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        with recorder.track("embedding", self.model_name) as call:
            call.content(input=text)
            return self._embedder.embed_query(text)

