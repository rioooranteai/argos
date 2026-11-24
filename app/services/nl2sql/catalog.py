"""The CATALOG block of the NL2SQL prompt: which products exist in the active documents.

Without it the model only sees the schema and guesses names and categories from the user's words
(e.g. `LIKE '%iuran tahunan%'` for "annual fee", or `'%icbc gold%'` for a product stored as brand
"PT Bank ICBC Indonesia" + product "Visa Gold"). The catalog is built from the `features` rows of
the active sources — no LLM call — and kept small:

    - doc 'D2' — product_terms: RIPLAY Kartu Kredit ICBC
      PT Bank ICBC Indonesia: UP Gold*, UP Platinum*, Visa Gold*, Visa Platinum*

`*` = the product has a price; a model/part number follows the name in brackets
("Catalyst 6500 16-port GigE Module [WS-X6516-GBIC]*"). At most `names_per_doc` names per document (the names that share a
word with the question first, so a large price list still shows the product asked about) and at
most `max_chars` for the whole block.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.services.nl2sql.executor import doc_aliases

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) > 1}


def _load(db_path: Path, version_ids: list[str]) -> dict[str, list[tuple[str, str, bool]]]:
    """version_id → [(brand, product label, has_price)] in document order, one entry per product.

    The label is the product name plus its model/part number in brackets when it has one, so the
    model can filter on a code the user types ("WS-X6516-GBIC") as well as on the name.
    """
    placeholders = ", ".join("?" for _ in version_ids)
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = src.execute(
            "SELECT version_id, COALESCE(brand_name, ''), product_name, COALESCE(model_code, ''), "
            "MAX(price IS NOT NULL) "
            f"FROM features WHERE version_id IN ({placeholders}) AND product_name IS NOT NULL "
            "GROUP BY version_id, COALESCE(brand_name, ''), product_name, COALESCE(model_code, '') "
            "ORDER BY version_id, MIN(rowid)",
            list(version_ids),
        ).fetchall()
    finally:
        src.close()
    out: dict[str, list[tuple[str, str, bool]]] = {}
    for vid, brand, product, code, priced in rows:
        label = product.strip() + (f" [{code.strip()}]" if code.strip() else "")
        out.setdefault(vid, []).append((brand.strip(), label, bool(priced)))
    return out


def _pick(products: list[tuple[str, str, bool]], question: set[str], limit: int):
    """The products sharing the most words (or codes) with the question first, then document order."""
    if len(products) <= limit:
        return products
    ranked = sorted(
        range(len(products)),
        key=lambda i: (-len(question & _tokens(products[i][1] + " " + products[i][0])), i),
    )
    keep = sorted(ranked[:limit])
    return [products[i] for i in keep]


def build_catalog(
    db_path: Path, version_ids: list[str], question: str,
    labels: dict[str, str] | None = None, names_per_doc: int = 30, max_chars: int = 3200,
) -> str:
    """The catalog text, or "" when the active sources have no products."""
    if not version_ids:
        return ""
    try:
        by_version = _load(db_path, version_ids)
    except sqlite3.Error:
        return ""
    labels = labels or {}
    aliases = doc_aliases(version_ids)
    q_tokens = _tokens(question)
    blocks: list[str] = []
    used = 0
    with_products = [v for v in version_ids if v in by_version]
    for n, vid in enumerate(with_products):
        products = by_version[vid]
        shown = _pick(products, q_tokens, names_per_doc)
        lines = [f"- doc '{aliases[vid]}'" + (f" — {labels[vid]}" if labels.get(vid) else "")]
        by_brand: dict[str, list[str]] = {}
        for brand, product, priced in shown:
            by_brand.setdefault(brand, []).append(product + ("*" if priced else ""))
        for brand, names in by_brand.items():
            lines.append(f"  {brand or '(no brand)'}: {', '.join(names)}")
        if len(products) > len(shown):
            lines.append(f"  (+{len(products) - len(shown)} more products)")
        text = "\n".join(lines)
        if blocks and used + len(text) > max_chars:
            blocks.append(f"(+{len(with_products) - n} more documents with products)")
            break
        blocks.append(text)
        used += len(text)
    return "\n".join(blocks)
