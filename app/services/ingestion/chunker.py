from __future__ import annotations

import hashlib
import logging
from typing import Iterator

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.ingestion.base.chunker import BaseChunker
from app.services.ingestion.exceptions import ChunkingError
from app.services.ingestion.models import Chunk, DocumentElement, ElementType

logger = logging.getLogger(__name__)

_ATOMIC_TYPES = {ElementType.TABLE, ElementType.HEADING, ElementType.CAPTION}

# Config chunking per tipe konten
_CHUNK_CONFIG: dict[ElementType, dict] = {
    ElementType.TEXT: {"chunk_size": 600, "chunk_overlap": 80},
    ElementType.LIST_ITEM: {"chunk_size": 400, "chunk_overlap": 60},
    ElementType.FIGURE: {"chunk_size": 400, "chunk_overlap": 50},
    ElementType.PAGE_HEADER: {"chunk_size": 200, "chunk_overlap": 0},
    ElementType.PAGE_FOOTER: {"chunk_size": 200, "chunk_overlap": 0},
}


class ContentAwareChunker(BaseChunker):
    """
    Chunker yang memperlakukan setiap tipe elemen secara berbeda dan
    menyuntikkan metadata langsung ke dalam teks (Context Injection)
    agar AI tidak kehilangan konteks di Vector DB.
    """

    def chunk(
            self,
            elements: list[DocumentElement],
            source_doc: str,
            competitor_name: str,
    ) -> list[Chunk]:
        chunks: list[Chunk] = []
        chunk_index = 0

        for element in elements:
            try:
                for text_piece in self._split_element(element):

                    # --- CONTEXT INJECTION ---
                    # Suntikkan metadata ke dalam teks agar nempel selamanya di VDB
                    konteks = f"[Dokumen: {source_doc} | Bab: {element.section_heading}]"
                    if competitor_name and competitor_name != "Unknown":
                        konteks += f" [Kompetitor: {competitor_name}]"

                    enriched_text = f"{konteks}\n{text_piece}"
                    # -------------------------

                    chunks.append(
                        Chunk(
                            chunk_id=self._make_chunk_id(source_doc, chunk_index),
                            text=enriched_text,  # Masukkan teks yang sudah diperkaya
                            source_doc=source_doc,
                            competitor_name=competitor_name,
                            page_number=element.page_number,
                            content_type=element.element_type,
                            section_heading=element.section_heading,
                            chunk_index=chunk_index,
                        )
                    )
                    chunk_index += 1

            except Exception as e:
                raise ChunkingError(element.element_type.value, str(e)) from e

        logger.info(
            "Chunker: %d chunk dari %d elemen (%s)",
            len(chunks), len(elements), source_doc,
        )
        return chunks

    def _split_element(self, element: DocumentElement) -> Iterator[str]:
        content = element.content.strip()
        if not content:
            return

        if element.element_type in _ATOMIC_TYPES:
            yield content
            return

        config = _CHUNK_CONFIG.get(
            element.element_type,
            {"chunk_size": 600, "chunk_overlap": 80},
        )
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=config["chunk_size"],
            chunk_overlap=config["chunk_overlap"],
            separators=["\n\n", "\n", ". ", " "],
        )
        for piece in splitter.split_text(content):
            if piece.strip():
                yield piece.strip()

    @staticmethod
    def _make_chunk_id(source_doc: str, index: int) -> str:
        raw = f"{source_doc}::{index}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]