"""Sidik teks dokumen untuk saran "mirip dengan dokumen Library" (DESIGN_GROUP_A.md §6.3).

Metode (dikalibrasi pada data/eval_corpus, lihat IMPLEMENTATION_PLAN_AB.md §4 Tahap 3):
  - teks diambil dari text layer PDF (pypdfium2, tanpa Docling) atau file MD apa adanya;
  - huruf kecil, setiap angka → "#", agar perubahan harga (inti versi baru sebuah
    price list) tidak menurunkan skor;
  - shingle 5 kata → sketsa bottom-k (k nilai hash 64-bit terkecil);
  - skor = estimasi Jaccard dari dua sketsa.

Hanya saran: hasilnya tidak pernah memindahkan dokumen tanpa konfirmasi user.
"""
from __future__ import annotations

import hashlib
import logging
import re
import struct
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

SHINGLE_WORDS = 5
SKETCH_SIZE = 256
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"\w+|#")
_PACK = struct.Struct(">Q")


@dataclass(frozen=True)
class SimilarDocument:
    document_id: str
    display_name: str
    score: float


def extract_text(path: Path, ext: str) -> str:
    """Teks mentah dokumen. String kosong bila tidak bisa dibaca (mis. PDF hasil scan)."""
    try:
        if ext == ".md":
            return path.read_text(encoding="utf-8", errors="ignore")
        if ext == ".pdf":
            import pypdfium2 as pdfium  # dependensi Docling, sudah terpasang

            pdf = pdfium.PdfDocument(str(path))
            try:
                parts = []
                for i in range(len(pdf)):
                    page = pdf[i]
                    textpage = page.get_textpage()
                    try:
                        parts.append(textpage.get_text_range())
                    finally:
                        textpage.close()
                        page.close()
                return "\n".join(parts)
            finally:
                pdf.close()
    except Exception:  # hanya untuk saran: gagal → tanpa saran
        logger.info("Teks untuk sidik kemiripan tidak bisa dibaca (%s).", path.name, exc_info=True)
    return ""


def _shingle_hashes(text: str) -> set[int]:
    words = _WORD.findall(_NUMBER.sub("#", text.lower()))
    hashes: set[int] = set()
    for i in range(len(words) - SHINGLE_WORDS + 1):
        shingle = " ".join(words[i : i + SHINGLE_WORDS]).encode()
        hashes.add(int.from_bytes(hashlib.blake2b(shingle, digest_size=8).digest(), "big"))
    return hashes


def fingerprint(text: str, min_shingles: int) -> bytes | None:
    """Sketsa bottom-k (k × 8 byte, urut naik). None bila teks terlalu sedikit untuk
    dibandingkan dengan andal."""
    hashes = _shingle_hashes(text)
    if len(hashes) < min_shingles:
        return None
    return b"".join(_PACK.pack(h) for h in sorted(hashes)[:SKETCH_SIZE])


def _decode(sketch: bytes) -> list[int]:
    return [v for (v,) in _PACK.iter_unpack(sketch)]


def similarity(a: bytes, b: bytes) -> float:
    """Estimasi Jaccard dua sketsa bottom-k (eksak bila kedua himpunan ≤ k)."""
    sa, sb = _decode(a), _decode(b)
    if not sa or not sb:
        return 0.0
    k = min(SKETCH_SIZE, len(sa), len(sb))
    union_bottom = sorted(set(sa) | set(sb))[:k]
    set_a, set_b = set(sa), set(sb)
    both = sum(1 for h in union_bottom if h in set_a and h in set_b)
    return both / len(union_bottom)


def most_similar(
    sketch: bytes,
    candidates: list[tuple[str, str, bytes]],
    threshold: float,
) -> SimilarDocument | None:
    """Kandidat (document_id, nama, sketsa) dengan skor tertinggi ≥ ``threshold``."""
    best: SimilarDocument | None = None
    for document_id, name, other in candidates:
        score = similarity(sketch, other)
        if score >= threshold and (best is None or score > best.score):
            best = SimilarDocument(document_id, name, round(score, 3))
    return best
