from __future__ import annotations

from abc import ABC, abstractmethod

class BaseEmbedder(ABC):

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """
        Embed list teks sekaligus (batch).
        Digunakan saat ingestion untuk embed banyak chunk sekaligus.
        Urutan output harus sama dengan urutan input.
        """

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """
        Embed satu teks query.
        Digunakan saat retrieval untuk embed pertanyaan user.
        """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Dimensi vector yang dihasilkan (misal: 1536 untuk OpenAI)."""