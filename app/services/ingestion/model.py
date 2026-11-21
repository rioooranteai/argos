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
    """One parsed element (text/table/image), in document order."""

    element_type: ElementType
    content: str
    page_number: int = 0
    section_heading: str = ""
    image_bytes: bytes | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass
class Section:
    """A document section per heading (DESIGN_GROUP_A.md §3).

    ``section_hash`` is computed from the CONTENT only (text + image hashes), without page
    numbers or positions — a section that moves to another page is still recognised.
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
    """One extraction LLM call: one or more sections (DESIGN_GROUP_B.md §7)."""

    unit_hash: str
    sections: list[Section]
    labels: dict[str, str]  # label "S1" → section_hash

    def prompt_text(self) -> str:
        blocks = []
        for label, section in zip(self.labels, self.sections, strict=True):
            heading = section.heading or "(untitled)"
            blocks.append(f"[{label}] {heading}\n{section.text}")
        return "\n\n".join(blocks)

