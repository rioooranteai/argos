from __future__ import annotations
from abc import ABC, abstractmethod
from app.services.ingestion.models import Chunk, DocumentElement

class BaseChunker(ABC):
    """
    Model Contract :
    - chunk
    """
    @abstractmethod
    def chunk(
        self,
        elements: list[DocumentElement],
        source_doc: str,
        competitor_name: str,
    ) -> list[Chunk]:
        """
        Pecah elemen dokumen menjadi chunk-chunk kecil.

        Aturan yang harus dipatuhi implementasi:
         - Tabel tidak boleh dipotong di tengah (atomik)
         - Heading menjadi batas chunk, bukan isi chunk terpisah
         - List item digabung dengan heading di atasnya
         - chunk_id harus unik dan deterministik

        Raises:
         ChunkingError: jika terjadi error saat chunking.
        """