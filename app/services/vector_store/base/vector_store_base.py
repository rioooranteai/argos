from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.ingestion.model import IndexChunk
from app.services.vector_store.model import SearchHit


class BaseVectorStoreProvider(ABC):
    @abstractmethod
    def add_chunks(self, chunks: list[IndexChunk]) -> list[str]:
        """Embed lalu simpan/perbarui chunk. Return ID yang tersimpan."""

    @abstractmethod
    def search(self, query: str, version_ids: list[str] | None, limit: int = 5) -> list[SearchHit]:
        """Cari chunk paling relevan, hanya dari `version_ids` (None = tanpa filter)."""

    @abstractmethod
    def delete_version(self, version_id: str) -> None:
        """Hapus semua chunk milik satu versi dokumen."""

    @abstractmethod
    def count_version(self, version_id: str) -> int:
        """Jumlah chunk milik satu versi (untuk pemeriksaan & test)."""
