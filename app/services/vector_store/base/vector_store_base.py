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
        """Embed lalu simpan/perbarui chunk.

        ``reuse`` memetakan teks chunk → ID chunk lama yang teksnya identik. Vektor
        chunk lama itu dipakai ulang (tanpa memanggil embedder); chunk lama tidak
        diubah. Chunk lama yang ternyata sudah hilang di-embed seperti biasa.
        """

    @abstractmethod
    def version_texts(self, version_id: str) -> dict[str, str]:
        """Teks chunk → ID chunk untuk satu versi (bahan ``reuse``)."""

    @abstractmethod
    def search(self, query: str, version_ids: list[str] | None, limit: int = 5) -> list[SearchHit]:
        """Cari chunk paling relevan, hanya dari `version_ids` (None = tanpa filter)."""

    @abstractmethod
    def delete_version(self, version_id: str) -> None:
        """Hapus semua chunk milik satu versi dokumen."""

    @abstractmethod
    def count_version(self, version_id: str) -> int:
        """Jumlah chunk milik satu versi (untuk pemeriksaan & test)."""
