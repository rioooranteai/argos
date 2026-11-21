from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from app.services.ingestion.model import IndexChunk
from app.services.vector_store.model import AddChunksResult, SearchHit


class BaseVectorStoreProvider(ABC):
    @abstractmethod
    def add_chunks(
        self, chunks: list[IndexChunk], reuse: Mapping[str, str] | None = None
    ) -> AddChunksResult:
        """Embed, then store/update chunks.

        ``reuse`` maps a chunk text → the ID of an old chunk with identical text. That
        old chunk's vector is reused (without calling the embedder); the old chunk is
        not changed. Old chunks that turn out to be gone are embedded as usual.
        """

    @abstractmethod
    def version_texts(self, version_id: str) -> dict[str, str]:
        """Chunk text → chunk ID for one version (input for ``reuse``)."""

    @abstractmethod
    def search(self, query: str, version_ids: list[str] | None, limit: int = 5) -> list[SearchHit]:
        """Find the most relevant chunks, only from `version_ids` (None = no filter)."""

    @abstractmethod
    def delete_version(self, version_id: str) -> None:
        """Delete every chunk of one document version."""

    @abstractmethod
    def count_version(self, version_id: str) -> int:
        """Number of chunks of one version (for checks & tests)."""

    def heartbeat(self) -> None:
        """Raise if the vector store cannot be reached (/health/ready)."""
        raise NotImplementedError
