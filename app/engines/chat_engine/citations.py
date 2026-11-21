"""Numbered citations taken from the data, not made up by the LLM (DESIGN_GROUP_A.md §8.4).

Each (document version, page) pair that appears in the retrieved data gets a
`[n]` label. The LLM may only refer to the labels it is given; the API response
only includes the labels actually used in the answer.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.services.notebook.model import ActiveSource

_LABEL_RE = re.compile(r"\[(\d{1,3})\]")


@dataclass(frozen=True)
class Citation:
    label: int
    version_id: str
    document_id: str
    display_name: str
    version_no: int
    uploaded_at: str  # YYYY-MM-DD
    page_number: int | None
    section_heading: str | None

    def to_dict(self) -> dict:
        return asdict(self)


class CitationRegistry:
    def __init__(self, sources: list[ActiveSource]) -> None:
        self._sources = {s.version_id: s for s in sources}
        self._by_key: dict[tuple[str, int | None], Citation] = {}

    def label_for(
        self, version_id: str | None, page_number: int | None, section_heading: str | None = None
    ) -> str:
        """The `[n]` label for a fact; an empty string when its version is not an active source."""
        source = self._sources.get(version_id or "")
        if source is None:
            return ""
        page = int(page_number) if page_number not in (None, "") else None
        key = (source.version_id, page)
        citation = self._by_key.get(key)
        if citation is None:
            citation = Citation(
                label=len(self._by_key) + 1,
                version_id=source.version_id,
                document_id=source.document_id,
                display_name=source.display_name,
                version_no=source.version_no,
                uploaded_at=source.uploaded_at.date().isoformat() if source.uploaded_at else "",
                page_number=page,
                section_heading=section_heading or None,
            )
            self._by_key[key] = citation
        return f"[{citation.label}]"

    def legend(self) -> str:
        """The label list for the synthesizer prompt."""
        lines = []
        for c in self._by_key.values():
            where = f", p. {c.page_number}" if c.page_number else ""
            lines.append(f"[{c.label}] {c.display_name} v{c.version_no} (uploaded {c.uploaded_at}{where})")
        return "\n".join(lines)

    def coverage(self) -> str:
        names = [f"{s.display_name} v{s.version_no}" for s in self._sources.values()]
        return f"{len(names)} source(s) ({', '.join(names)})"

    def used_in(self, answer: str) -> list[Citation]:
        by_label = {c.label: c for c in self._by_key.values()}
        used = sorted({int(m) for m in _LABEL_RE.findall(answer)} & by_label.keys())
        return [by_label[n] for n in used]
