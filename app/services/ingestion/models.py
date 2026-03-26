from __future__ import annotations

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
    element_type: ElementType
    content: str
    page_number: int = 0
    section_heading: str = ""
    image_bytes: bytes | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    chunk_id: str
    text: str
    source_doc: str
    competitor_name: str | None = None
    page_number: int
    content_type: ElementType
    section_heading: str
    chunk_index: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class EmbeddedChunk(BaseModel):
    chunk: Chunk
    vector: list[float]
