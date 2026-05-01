import hashlib
import logging
from pathlib import Path
from typing import List

from app.services.ingestion.model import DocumentElement, Chunk

logger = logging.getLogger(__name__)

class ContentAwareChunker:
    """
    Tugas barunya adalah sebagai 'Adapter & Injector':
    1. Menyuntikkan metadata (Nama Kompetitor, Bab) langsung ke dalam teks (Context Injection).
    2. Mengubah DocumentElement menjadi format Chunk standar untuk Chroma DB.
    """

    def generate_chunk_id(self, text: str, page: int) -> str:
        """Membuat ID unik berbasis hash dari isi teks dan halamannya."""
        unique_string = f"{page}-{text}"
        return hashlib.md5(unique_string.encode("utf-8")).hexdigest()[:16]

    def process_elements(
        self,
        elements: List[DocumentElement],
        document_id: str
    ) -> List[Chunk]:
        """Memproses elemen dari Loader dan menyiapkannya untuk Vector DB."""
        chunks: List[Chunk] = []

        for i, element in enumerate(elements):
            if not element.content or not element.content.strip():
                continue

            raw_source = element.metadata.get("source", "Unknown")
            clean_filename = Path(raw_source).name

            element.metadata["source"] = clean_filename
            element.metadata["document_id"] = document_id

            injected_text = (
                f"[Dokumen: {clean_filename}]\n"
                f"{element.content}"
            )

            chunk_id = self.generate_chunk_id(injected_text, element.page_number)

            chunk = Chunk(
                chunk_id=chunk_id,
                source_doc=clean_filename,
                chunk_index=i,
                page_number=element.page_number,
                section_heading=element.section_heading,
                content_type=element.element_type,
                text=injected_text,
                metadata=element.metadata
            )

            if element.image_bytes:
                chunk.image_bytes = element.image_bytes

            chunks.append(chunk)

        return chunks