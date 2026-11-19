from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ElementType(str, Enum):
    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    LIST_ITEM = "list_item"
    FIGURE = "figure"
    CAPTION = "caption"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"


class DocumentElement(BaseModel):
    """Satu elemen hasil parsing (teks/tabel/gambar), dalam urutan dokumen."""

    element_type: ElementType
    content: str
    page_number: int = 0
    section_heading: str = ""
    image_bytes: bytes | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class Section:
    """Bagian dokumen per heading (DESIGN_GROUP_A.md §3).

    ``section_hash`` dihitung dari ISI saja (teks + hash gambar), tanpa nomor
    halaman atau posisi — bagian yang bergeser halaman tetap dikenali.
    """

    section_hash: str
    heading: str
    parent_heading: str
    page_start: int
    ord: int
    elements: list[DocumentElement] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(e.content for e in self.elements if e.content.strip())


@dataclass
class ExtractionUnit:
    """Satu panggilan LLM ekstraksi: satu atau beberapa bagian (DESIGN_GROUP_B.md §7)."""

    unit_hash: str
    sections: list[Section]
    labels: dict[str, str]  # label "S1" → section_hash

    def prompt_text(self) -> str:
        blocks = []
        for label, section in zip(self.labels, self.sections, strict=True):
            heading = section.heading or "(tanpa judul)"
            blocks.append(f"[{label}] {heading}\n{section.text}")
        return "\n\n".join(blocks)


@dataclass(frozen=True)
class IndexChunk:
    """Satu potongan teks untuk vector store."""

    chunk_id: str
    text: str
    metadata: dict[str, Any]
