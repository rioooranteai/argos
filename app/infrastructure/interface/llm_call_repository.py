from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from app.services.observability.model import LLMCall


class BaseLLMCallRepository(ABC):
    @abstractmethod
    def insert_many(self, calls: Sequence[LLMCall]) -> None: ...

    @abstractmethod
    def purge_older_than(self, days: int) -> int:
        """Delete records older than ``days`` days. Returns the number of deleted rows."""

    @abstractmethod
    def list_for_message(self, message_id: str) -> list[LLMCall]: ...
