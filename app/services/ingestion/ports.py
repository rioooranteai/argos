"""Cache of AI results. Also works as a checkpoint: a job restarted from scratch
does not pay again for Vision/extraction work already done."""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseCacheRepository(ABC):
    @abstractmethod
    def get_vision(self, image_hash: str, model: str) -> str | None: ...

    @abstractmethod
    def put_vision(self, image_hash: str, model: str, description: str) -> None: ...

    @abstractmethod
    def get_extraction(self, unit_hash: str, pipeline_version: str) -> str | None:
        """The unit's extraction result as JSON, or None."""

    @abstractmethod
    def put_extraction(self, unit_hash: str, pipeline_version: str, result_json: str) -> None: ...
