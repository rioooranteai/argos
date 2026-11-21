"""Sections, section_hash, extraction units, and chunk IDs."""
from __future__ import annotations

from app.services.ingestion.chunker import build_index_chunks, build_sections, build_units
from app.tools.document_parser.base import DocumentElement, ElementType


def el(text: str, heads: list[str], page: int = 1, kind=ElementType.TEXT) -> DocumentElement:
    return DocumentElement(
        element_type=kind, content=text, page_number=page,
        section_heading=heads[-1] if heads else "", metadata={"headings": heads},
    )


def fig(page: int, data: bytes = b"img") -> DocumentElement:
    return DocumentElement(element_type=ElementType.FIGURE, content="", page_number=page, image_bytes=data)


def words(n: int) -> str:
    return " ".join(["kata"] * n)


def test_groups_consecutive_elements_by_heading():
    sections = build_sections([
        el("intro", ["Pendahuluan"]),
        el("harga A", ["Harga"]),
        el("harga B", ["Harga"]),
        el("spek", ["Spesifikasi"]),
    ])
    assert [s.heading for s in sections] == ["Pendahuluan", "Harga", "Spesifikasi"]
    assert len(sections[1].elements) == 2


def test_section_hash_ignores_page_shift():
    """Pages shift (e.g. a page inserted at the front) → the section hash stays the same."""
    v1 = build_sections([el("Avanza 230 jt", ["Harga"], page=4)])
    v2 = build_sections([el("Avanza 230 jt", ["Harga"], page=5)])
    assert v1[0].section_hash == v2[0].section_hash
    assert v2[0].page_start == 5


def test_section_hash_changes_with_content():
    v1 = build_sections([el("Avanza 230 jt", ["Harga"])])
    v2 = build_sections([el("Avanza 235 jt", ["Harga"])])
    assert v1[0].section_hash != v2[0].section_hash


def test_section_hash_ignores_whitespace_and_case():
    v1 = build_sections([el("Avanza  230 JT", ["Harga"])])
    v2 = build_sections([el("avanza 230 jt", ["Harga"])])
    assert v1[0].section_hash == v2[0].section_hash


def test_figure_identity_is_image_bytes_not_description():
    a = build_sections([el("t", ["H"]), fig(1, b"same")])
    b = build_sections([el("t", ["H"]), fig(1, b"same")])
    c = build_sections([el("t", ["H"]), fig(1, b"other")])
    assert a[0].section_hash == b[0].section_hash != c[0].section_hash


def test_figures_placed_by_page():
    sections = build_sections([el("a", ["A"], page=1), el("b", ["B"], page=3), fig(2), fig(4)])
    assert [e.element_type for e in sections[0].elements] == [ElementType.TEXT, ElementType.FIGURE]
    assert [e.element_type for e in sections[1].elements] == [ElementType.TEXT, ElementType.FIGURE]


def test_duplicate_sections_get_distinct_hashes():
    sections = build_sections([el("footer", ["F"]), el("x", ["G"]), el("footer", ["F"])])
    hashes = [s.section_hash for s in sections]
    assert len(set(hashes)) == 3


def _count(text: str) -> int:
    return len(text.split())


def test_small_sections_merged_within_same_parent():
    sections = build_sections([
        el(words(50), ["Mobil", "Avanza"]),
        el(words(50), ["Mobil", "Veloz"]),
        el(words(50), ["Motor", "Beat"]),
    ])
    units = build_units(sections, _count, min_section_tokens=300, max_unit_tokens=4000)
    assert [len(u.sections) for u in units] == [2, 1]
    assert list(units[0].labels) == ["S1", "S2"]
    assert "[S1] Avanza" in units[0].prompt_text()


def test_large_sections_not_merged():
    sections = build_sections([el(words(400), ["P", "A"]), el(words(400), ["P", "B"])])
    units = build_units(sections, _count, min_section_tokens=300, max_unit_tokens=4000)
    assert len(units) == 2


def test_oversized_section_split_keeps_section_hash():
    sections = build_sections([
        el(words(3000), ["Katalog"]),
        el(" ".join(["lain"] * 3000), ["Katalog"]),
    ])
    assert len(sections) == 1
    units = build_units(sections, _count, min_section_tokens=300, max_unit_tokens=4000)
    assert len(units) == 2
    assert {u.labels["S1"] for u in units} == {sections[0].section_hash}
    assert units[0].unit_hash != units[1].unit_hash


def test_chunk_ids_unique_per_version():
    sections = build_sections([el("Avanza 230 jt", ["Harga"], page=2)])
    a = build_index_chunks(sections, "d1", "v1", "Pricelist")
    b = build_index_chunks(sections, "d1", "v2", "Pricelist")
    assert a[0].chunk_id != b[0].chunk_id
    assert a[0].metadata["version_id"] == "v1"
    assert a[0].metadata["section_hash"] == sections[0].section_hash
    assert a[0].metadata["page_number"] == 2
    assert a[0].text.startswith("[Document: Pricelist]")
