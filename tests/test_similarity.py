"""Sidik teks & skor kemiripan (Tahap 3, A §6.3)."""
from __future__ import annotations

import random

from app.services.library.similarity import (
    SKETCH_SIZE,
    extract_text,
    fingerprint,
    most_similar,
    similarity,
)
from tests.library_helpers import make_pdf

WORDS = (
    "harga mobil garansi mesin bensin diesel transmisi otomatis manual cicilan bunga tenor "
    "dealer servis berkala suku cadang warna interior kursi kabin bagasi roda velg lampu "
    "kamera sensor parkir layar sentuh audio speaker pendingin kabin airbag rem cakram"
).split()


def _doc(seed: int, n: int = 600) -> str:
    rnd = random.Random(seed)
    lines = []
    for i in range(n // 10):
        lines.append(" ".join(rnd.choice(WORDS) for _ in range(9)) + f" Rp {rnd.randint(100, 999)}.000")
    return "\n".join(lines)


def test_identical_text_scores_one():
    fp = fingerprint(_doc(1), 50)
    assert similarity(fp, fp) == 1.0


def test_price_changes_do_not_lower_score():
    text = _doc(1)
    repriced = text.replace("Rp 1", "Rp 9").replace(".000", ".500")
    assert similarity(fingerprint(text, 50), fingerprint(repriced, 50)) == 1.0


def test_unrelated_documents_score_low():
    assert similarity(fingerprint(_doc(1), 50), fingerprint(_doc(2), 50)) < 0.1


def test_small_edit_stays_above_threshold():
    text = _doc(1)
    lines = text.split("\n")
    edited = "\n".join(lines[:-2] + ["promo baru akhir tahun untuk semua tipe kendaraan"])
    assert similarity(fingerprint(text, 50), fingerprint(edited, 50)) >= 0.9


def test_sketch_is_bounded_and_sorted():
    fp = fingerprint(_doc(1, n=5000), 50)
    assert len(fp) == SKETCH_SIZE * 8
    values = [int.from_bytes(fp[i : i + 8], "big") for i in range(0, len(fp), 8)]
    assert values == sorted(values)


def test_too_little_text_has_no_fingerprint():
    assert fingerprint("hanya beberapa kata di sini", 200) is None
    assert fingerprint("", 1) is None


def test_most_similar_picks_best_above_threshold():
    base = fingerprint(_doc(1), 50)
    near = fingerprint(_doc(1).replace("Rp", "IDR", 1), 50)
    far = fingerprint(_doc(3), 50)
    best = most_similar(base, [("far", "Jauh", far), ("near", "Dekat", near)], 0.9)
    assert best is not None and best.document_id == "near" and best.display_name == "Dekat"
    assert most_similar(base, [("far", "Jauh", far)], 0.9) is None


def test_extract_text_markdown_and_unreadable(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# Judul\nisi dokumen", encoding="utf-8")
    assert "isi dokumen" in extract_text(md, ".md")

    blank_pdf = tmp_path / "b.pdf"
    blank_pdf.write_bytes(make_pdf(1))  # PDF tanpa text layer (mis. hasil scan)
    assert extract_text(blank_pdf, ".pdf").strip() == ""

    broken = tmp_path / "c.pdf"
    broken.write_bytes(b"bukan pdf")
    assert extract_text(broken, ".pdf") == ""
