"""Cache hasil AI. Juga berfungsi sebagai checkpoint: job yang diulang dari awal
tidak membayar ulang Vision/ekstraksi yang sudah selesai (DESIGN_GROUP_B.md §9)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseCacheRepository(ABC):
    @abstractmethod
    def get_vision(self, image_hash: str, model: str) -> str | None: ...

    @abstractmethod
    def put_vision(self, image_hash: str, model: str, description: str) -> None: ...

    @abstractmethod
    def get_extraction(self, unit_hash: str, pipeline_version: str) -> str | None:
        """JSON hasil ekstraksi unit, atau None."""

    @abstractmethod
    def put_extraction(self, unit_hash: str, pipeline_version: str, result_json: str) -> None: ...
