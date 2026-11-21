from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLLM(ABC):
    """
    The contract for every LLM provider.
    Used by: the extraction agent, RAG chain, NL-to-SQL agent, router.
    """

    @abstractmethod
    def invoke(self, prompt: str, system: str | None = None) -> str:
        """
        Send a prompt to the LLM and return the response as a string.
        For general use: RAG answers, router classification.
        """

    @abstractmethod
    async def ainvoke(self, prompt: str, system: str | None = None) -> str:
        """Async version of invoke for FastAPI endpoints."""

