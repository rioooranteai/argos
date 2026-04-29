from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Type, Any

from pydantic import BaseModel


class BaseLLM(ABC):
    """
    Kontrak untuk semua LLM provider.
    Dipakai oleh: extraction agent, RAG chain, NL-to-SQL agent, router.
    """

    @abstractmethod
    def invoke(self, prompt: str, system: str | None = None) -> str:
        """
        Kirim prompt ke LLM, kembalikan response sebagai string.
        Untuk penggunaan umum: RAG answer, router classification.
        """

    @abstractmethod
    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        """Async version dari invoke untuk endpoint FastAPI."""

    @abstractmethod
    def with_structured_output(self, schema: Type[BaseModel]) -> "BaseLLM":
        """
        Return instance LLM yang output-nya dipaksa sesuai Pydantic schema.
        Digunakan oleh extraction agent untuk output terstruktur.
        """
