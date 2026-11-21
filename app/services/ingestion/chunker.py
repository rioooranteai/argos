"""Document sections, extraction units and vector chunks (DESIGN_GROUP_A.md §3, B §7).

Flow:
    Docling elements → build_sections()      sections per heading + content-only section_hash
                     → build_units()         small sections merged → extraction units
                     → build_index_chunks()  one chunk per element for the vector store
"""
from __future__ import annotations

import hashlib
import re
from collections.abc import Callable

from app.services.ingestion.model import (
    DocumentElement,
    ElementType,
    ExtractionUnit,
    Section,
)
from app.tools.vector_store.base import IndexChunk

_WS = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS.sub(" ", text).strip().lower()


def image_hash(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _element_fingerprint(el: DocumentElement) -> str:
    if el.element_type == ElementType.FIGURE:
        # Vision descriptions are not deterministic → an image's identity = the hash of its bytes.
        return "img:" + (el.metadata.get("image_hash") or "")
    return _normalize(el.content)


def _section_hash(heading: str, elements: list[DocumentElement]) -> str:
    digest = hashlib.sha256()
    digest.update(_normalize(heading).encode())
    for el in elements:
        digest.update(b"\x1f")
        digest.update(_element_fingerprint(el).encode())
    return digest.hexdigest()


def _headings(el: DocumentElement) -> list[str]:
    heads = el.metadata.get("headings")
    if heads:
        return [str(h) for h in heads]
    return [el.section_heading] if el.section_heading else []


def build_sections(elements: list[DocumentElement]) -> list[Section]:
    """Group consecutive elements with the same heading into one section.

    Docling returns images at the end (not in reading order), so each one goes into
    the last section that starts on or before the image's page.
    """
    for el in elements:
        if el.element_type == ElementType.FIGURE and el.image_bytes:
            el.metadata["image_hash"] = image_hash(el.image_bytes)

    text_elements = [e for e in elements if e.element_type != ElementType.FIGURE]
    figures = [e for e in elements if e.element_type == ElementType.FIGURE]

    groups: list[tuple[list[str], list[DocumentElement]]] = []
    for el in text_elements:
        heads = _headings(el)
        if groups and groups[-1][0] == heads:
            groups[-1][1].append(el)
        else:
            groups.append((heads, [el]))

    for fig in figures:
        target = None
        for heads, els in groups:
            if els[0].page_number <= fig.page_number:
                target = els
        if target is None:
            groups.append(([], [fig]))  # a document without text (e.g. images only)
        else:
            target.append(fig)

    sections: list[Section] = []
    seen: dict[str, int] = {}
    for ord_, (heads, els) in enumerate(groups):
        heading = heads[-1] if heads else ""
        h = _section_hash(heading, els)
        # Two sections with identical content (e.g. a repeated footer): tell them apart so the PK is unique.
        if h in seen:
            seen[h] += 1
            h = hashlib.sha256(f"{h}:{seen[h]}".encode()).hexdigest()
        else:
            seen[h] = 0
        sections.append(
            Section(
                section_hash=h,
                heading=heading,
                parent_heading=heads[-2] if len(heads) >= 2 else "",
                page_start=min(e.page_number for e in els),
                ord=ord_,
                elements=els,
            )
        )
    return sections


def build_units(
    sections: list[Section],
    count_tokens: Callable[[str], int],
    min_section_tokens: int,
    max_unit_tokens: int,
) -> list[ExtractionUnit]:
    """Merge small sections with their neighbours (same parent heading) up to the token limit.

    A section larger than ``max_unit_tokens`` is split per element into several
    units; every piece keeps the ``section_hash`` of its original section.
    """
    units: list[list[Section]] = []
    current: list[Section] = []
    current_tokens = 0

    for section, tokens in _split_oversized(sections, count_tokens, max_unit_tokens):
        can_merge = (
            current
            and current[-1].parent_heading == section.parent_heading
            and current_tokens + tokens <= max_unit_tokens
            and (tokens < min_section_tokens or current_tokens < min_section_tokens)
        )
        if can_merge:
            current.append(section)
            current_tokens += tokens
        else:
            if current:
                units.append(current)
            current, current_tokens = [section], tokens
    if current:
        units.append(current)

    result = []
    for group in units:
        labels = {f"S{i + 1}": s.section_hash for i, s in enumerate(group)}
        # Hash the unit content (not just section_hash) so the pieces of a large
        # section get different cache keys.
        unit_hash = hashlib.sha256(
            "|".join(f"{s.section_hash}:{_normalize(s.text)}" for s in group).encode()
        ).hexdigest()
        result.append(ExtractionUnit(unit_hash=unit_hash, sections=group, labels=labels))
    return result


def _split_oversized(
    sections: list[Section], count_tokens: Callable[[str], int], max_tokens: int
) -> list[tuple[Section, int]]:
    out: list[tuple[Section, int]] = []
    for section in sections:
        if not section.text.strip():
            continue
        tokens = count_tokens(section.text)
        if tokens <= max_tokens or len(section.elements) == 1:
            out.append((section, tokens))
            continue
        part: list[DocumentElement] = []
        part_tokens = 0
        for el in section.elements:
            t = count_tokens(el.content)
            if part and part_tokens + t > max_tokens:
                out.append((_part(section, part), part_tokens))
                part, part_tokens = [], 0
            part.append(el)
            part_tokens += t
        if part:
            out.append((_part(section, part), part_tokens))
    return out


def _part(section: Section, elements: list[DocumentElement]) -> Section:
    return Section(
        section_hash=section.section_hash,
        heading=section.heading,
        parent_heading=section.parent_heading,
        page_start=min(e.page_number for e in elements),
        ord=section.ord,
        elements=elements,
    )


def build_index_chunks(
    sections: list[Section], document_id: str, version_id: str, display_name: str
) -> list[IndexChunk]:
    """One chunk per non-empty element. ID = hash(version_id + content): unique across versions."""
    chunks: list[IndexChunk] = []
    seen: set[str] = set()
    for section in sections:
        for el in section.elements:
            if not el.content or not el.content.strip():
                continue
            text = f"[Document: {display_name}]\n{el.content.strip()}"
            chunk_id = hashlib.sha256(f"{version_id}\x1f{text}".encode()).hexdigest()[:32]
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            chunks.append(
                IndexChunk(
                    chunk_id=chunk_id,
                    text=text,
                    metadata={
                        "document_id": document_id,
                        "version_id": version_id,
                        "section_hash": section.section_hash,
                        "section_heading": section.heading,
                        "page_number": el.page_number,
                        "content_type": el.element_type.value,
                        "source": display_name,
                    },
                )
            )
    return chunks
