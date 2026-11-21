from __future__ import annotations

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts at once (batch).
        Used during ingestion to embed many chunks at once.
        The output order must match the input order.
        """

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """
        Embed one query text.
        Used during retrieval to embed the user's question.
        """
