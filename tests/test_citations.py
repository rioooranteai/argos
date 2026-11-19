"""Sitasi: label dari data, hanya label yang dipakai yang dikembalikan, agregat tanpa label."""
from __future__ import annotations

from datetime import datetime

from app.engines.chat_engine.citations import CitationRegistry
from app.engines.chat_engine.nodes import synthesizer
from app.services.nl2sql.service import NL2SQLResult
from app.services.notebook.model import ActiveSource

SOURCES = [
    ActiveSource("v1", "d1", "Pricelist Toyota", 2, datetime(2026, 2, 12)),
    ActiveSource("v2", "d2", "Brosur Dealer X", 1, datetime(2026, 2, 3)),
]


def test_labels_per_version_and_page():
    reg = CitationRegistry(SOURCES)
    assert reg.label_for("v1", 4) == "[1]"
    assert reg.label_for("v1", 4) == "[1]"   # sama → label sama
    assert reg.label_for("v1", 5) == "[2]"   # halaman lain → label baru
    assert reg.label_for("v2", 2) == "[3]"
    assert reg.label_for("v9", 1) == ""      # bukan sumber aktif → tanpa label


def test_used_in_returns_only_referenced_labels():
    reg = CitationRegistry(SOURCES)
    reg.label_for("v1", 4)
    reg.label_for("v2", 2)
    [c] = reg.used_in("Harga Avanza **Rp 230 jt** [1]. Label palsu [7] diabaikan.")
    assert (c.label, c.display_name, c.version_no, c.uploaded_at, c.page_number) == (
        1, "Pricelist Toyota", 2, "2026-02-12", 4,
    )


def test_sql_rows_get_labels_and_hide_citation_columns():
    reg = CitationRegistry(SOURCES)
    result = NL2SQLResult(
        status="ok",
        raw_data=[
            {"product_name": "Avanza", "price": 230.0, "version_id": "v1", "page_number": 4},
            {"product_name": "Avanza", "price": 232.0, "version_id": "v2", "page_number": 2},
        ],
        row_count=2,
    )
    text = synthesizer._format_sql_result(result, reg)
    assert "product_name=Avanza | price=230.0 [1]" in text
    assert "price=232.0 [2]" in text
    assert "version_id" not in text


def test_aggregate_rows_get_coverage_not_labels():
    reg = CitationRegistry(SOURCES)
    result = NL2SQLResult(status="ok", raw_data=[{"rata": 231.0}], row_count=1)
    text = synthesizer._format_sql_result(result, reg)
    assert "DATA AGREGAT" in text and "2 sumber" in text
    assert "[1]" not in text


def test_vector_hits_labelled_from_metadata():
    reg = CitationRegistry(SOURCES)
    text = synthesizer._format_vector_result(
        [{"text": "Veloz punya 7 kursi", "metadata": {"version_id": "v2", "page_number": 3}}], reg
    )
    assert text.endswith("Veloz punya 7 kursi [1]")
    assert "Brosur Dealer X v1" in reg.legend()


async def test_synthesizer_returns_used_citations():
    class LLM:
        async def ainvoke(self, prompt, system=None):
            assert "[1]" in prompt and "[DAFTAR SUMBER]" in prompt
            return "Avanza Rp 230 jt [1]."

    state = {
        "user_input": "harga avanza?",
        "messages": [],
        "sources": SOURCES,
        "sql_result": NL2SQLResult(
            status="ok",
            raw_data=[{"product_name": "Avanza", "price": 230.0, "version_id": "v1", "page_number": 4}],
            row_count=1,
        ),
        "vector_result": [],
    }
    out = await synthesizer.synthesizer_node(state, LLM())
    assert out["final_answer"] == "Avanza Rp 230 jt [1]."
    assert [c["label"] for c in out["citations"]] == [1]
    assert out["citations"][0]["version_id"] == "v1"
