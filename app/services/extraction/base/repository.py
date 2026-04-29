"""Port for feature persistence.

Decouples ExtractionService from any specific database implementation.
The default adapter is SQLiteFeatureRepository (see app.infrastructure.providers.repositories).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseFeatureRepository(ABC):
    """Contract for persisting extracted competitor features."""

    @abstractmethod
    def insert_batch(self, features: list[dict], document_id: str) -> None:
        """Insert a batch of feature dicts under the given document_id."""
        ...
