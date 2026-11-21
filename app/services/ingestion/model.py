from __future__ import annotations

from dataclasses import dataclass, field

from app.tools.document_parser.base import DocumentElement


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

