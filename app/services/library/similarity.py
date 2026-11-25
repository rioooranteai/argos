"""Document text fingerprints for the "similar to a Library document" suggestion.

Method (thresholds calibrated on sample documents, see SIMILARITY_THRESHOLD in config.py):
  - text comes from the PDF text layer (pypdfium2, no Docling) or the MD file as is;
  - lowercased, every digit → "#", so price changes (the point of a new price-list
    version) do not lower the score;
  - 5-word shingles → a bottom-k sketch (the k smallest 64-bit hash values);
  - score = the Jaccard estimate of two sketches.

Only a suggestion: it never moves a document without the user's confirmation.
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
    """The raw document text. An empty string when it cannot be read (e.g. a scanned PDF)."""
    try:
        if ext == ".md":
            return path.read_text(encoding="utf-8", errors="ignore")
        if ext == ".pdf":
            import pypdfium2 as pdfium  # a Docling dependency, already installed

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
    except Exception:  # only for the suggestion: failure → no suggestion
        logger.info("Could not read the text for the similarity fingerprint (%s).", path.name, exc_info=True)
    return ""


def _shingle_hashes(text: str) -> set[int]:
    words = _WORD.findall(_NUMBER.sub("#", text.lower()))
    hashes: set[int] = set()
    for i in range(len(words) - SHINGLE_WORDS + 1):
        shingle = " ".join(words[i : i + SHINGLE_WORDS]).encode()
        hashes.add(int.from_bytes(hashlib.blake2b(shingle, digest_size=8).digest(), "big"))
    return hashes


def fingerprint(text: str, min_shingles: int) -> bytes | None:
    """A bottom-k sketch (k × 8 bytes, ascending). None when there is too little text
    to compare reliably."""
    hashes = _shingle_hashes(text)
    if len(hashes) < min_shingles:
        return None
    return b"".join(_PACK.pack(h) for h in sorted(hashes)[:SKETCH_SIZE])


def _decode(sketch: bytes) -> list[int]:
    return [v for (v,) in _PACK.iter_unpack(sketch)]


def similarity(a: bytes, b: bytes) -> float:
    """Jaccard estimate of two bottom-k sketches (exact when both sets are ≤ k)."""
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
    """The candidate (document_id, name, sketch) with the highest score ≥ ``threshold``."""
    best: SimilarDocument | None = None
    for document_id, name, other in candidates:
        score = similarity(sketch, other)
        if score >= threshold and (best is None or score > best.score):
            best = SimilarDocument(document_id, name, round(score, 3))
    return best
