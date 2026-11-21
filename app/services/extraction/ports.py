"""Port for storing the processing results of one document version (sections + features)."""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.extraction.model import FeatureRow
from app.services.ingestion.model import Section


class BaseFeatureRepository(ABC):
    @abstractmethod
    def publish_version(
        self,
        document_id: str,
        version_id: str,
        sections: list[Section],
        features: list[FeatureRow],
        reuse_stats: dict[str, int] | None = None,
    ) -> bool:
        """In ONE transaction: write sections & features, mark the version `ready`
        (with its reuse statistics), and update the document's `latest_version_id`.
        Until this finishes, none of the version's data is visible to chat.

        Returns False (without writing anything) if cancellation was requested.
        """

    @abstractmethod
    def delete_version_content(self, version_id: str) -> None:
        """Delete a version's sections & features (cleanup of half-finished data)."""
