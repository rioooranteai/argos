"""Extraction lab: re-run profile + extraction with the current prompts on cached parses, and score them.

The full evaluation (run_eval.py) ingests every document again (Docling + vision take most of its
half hour). While the extraction prompt is tuned, only the profile and extraction stages change, so
this lab parses each document once (Docling + vision, cached under data/eval_lab/parsed/), then runs
the real DocumentProfiler and ExtractionService (no extraction cache) and scores the rows with the
scorer of run_eval.py.

Sets: extraction (notebook B), tuning (eval/tuning-files), validation (the frozen held-out set).
The held-out set is reported as aggregate scores only — its rows are neither printed nor saved —
so that it is never tuned on.

Usage:
    python eval/extraction_lab.py                          # tuning + extraction sets
    python eval/extraction_lab.py --sets validation        # held-out: aggregates only
    python eval/extraction_lab.py --files en_cisco_price_list_reseller.pdf --show
    python eval/extraction_lab.py --reparse                # parse again (e.g. after a Docling upgrade)
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import hashlib
import json
import os
import pickle
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = ROOT / "data" / "eval_lab"
SETS = {"extraction": "extraction-files", "tuning": "tuning-files", "validation": "validation-files"}


class _NoCache:
    """Extraction cache that never hits: every run uses the current prompt."""

    def get_extraction(self, *_):
        return None

    def put_extraction(self, *_):
        return None


async def _sections(pipeline, path: Path, reparse: bool):
    """Sections after Docling + vision, cached per file content."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    cache = LAB_DIR / "parsed" / f"{path.stem}-{digest}.pkl"
    if cache.exists() and not reparse:
        return pickle.loads(cache.read_bytes())
    from app.services.ingestion.chunker import build_sections

    cfg = pipeline._cfg
    pages = await asyncio.to_thread(pipeline._parser.a4_page_equivalents, str(path)) or 10
    elements = await pipeline._parser.parse(str(path), cfg.DOCLING_TIMEOUT_BASE + cfg.DOCLING_TIMEOUT_PER_PAGE * pages)
    sections = build_sections(elements)
    await pipeline._describer.describe_all(sections)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(pickle.dumps(sections))
    return sections


async def _extract(pipeline, path: Path, reparse: bool) -> tuple[list[dict], dict | None, float]:
    from app.services.extraction.service import ExtractionService
    from app.services.ingestion.chunker import build_units

    sections = await _sections(pipeline, path, reparse)
    t0 = time.perf_counter()
    profile = await pipeline._profiler.profile(path.stem, sections)
    context = profile.as_context() if profile else f"Title: {path.stem}"
    cfg, ext = pipeline._cfg, pipeline._extraction
    units = build_units(sections, pipeline._count_tokens, cfg.EXTRACTION_MIN_SECTION_TOKENS, cfg.EXTRACTION_MAX_UNIT_TOKENS)
    service = ExtractionService(provider=ext._provider, cache=_NoCache(), semaphore=ext._semaphore,
                                pipeline_version=ext._pipeline_version, timeout=ext._timeout)
    rows = await service.extract_units(units, context)
    return [dataclasses.asdict(r) for r in rows], (profile.model_dump() if profile else None), time.perf_counter() - t0


async def main_async(args) -> int:
    from fastapi import FastAPI

    from app.bootstrap import lifespan
    from app.tools.factory import build_llm

    import run_eval  # the scorer (eval/ is on sys.path)

    gt = json.loads((ROOT / "eval" / "ground_truth.json").read_text(encoding="utf-8"))
    out = {"started": datetime.now().isoformat(timespec="seconds"), "sets": {}}
    app = FastAPI()
    async with lifespan(app):
        pipeline = app.state.document_pipeline
        if args.max_unit_tokens:  # experiment: extraction unit size (AppConfig is frozen)
            object.__setattr__(pipeline._cfg, "EXTRACTION_MAX_UNIT_TOKENS", args.max_unit_tokens)
        judge = build_llm("router", 0.0) if args.judge else None
        for name in args.sets:
            corpus = ROOT / "eval" / SETS[name]
            paths = {p.name: p for p in sorted(corpus.glob("*.pdf")) if not args.files or p.name in args.files}
            if not paths:
                continue
            held_out = name == "validation"
            runs = []
            for rep in range(args.repeats):
                rows_by_file, profiles = {}, {}
                for fname, path in paths.items():
                    rows, profile, secs = await _extract(pipeline, path, args.reparse and rep == 0)
                    rows_by_file[fname], profiles[fname] = rows, profile
                    print(f"[{name}] {fname}: {len(rows)} rows in {secs:.0f} s", flush=True)
                docs = [d for d in gt[name]["documents"] if d["file"] in paths]
                score = await run_eval.score_extraction(docs, rows_by_file, judge, paths)
                if not held_out:
                    score["rows"] = rows_by_file  # inspected while tuning; never for the held-out set
                runs.append(score)
                _print(name, score, held_out, args.show, rows_by_file, profiles)
            out["sets"][name] = [_aggregate(s) if held_out else s for s in runs]
    LAB_DIR.mkdir(parents=True, exist_ok=True)
    dest = LAB_DIR / f"lab_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved: {dest}")
    return 0


def _aggregate(score: dict) -> dict:
    """Only the numbers of a held-out score: no product names, values or entities."""
    keep = ("per_field", "micro", "micro_core", "macro_f1", "products_found", "reference_products", "misses",
            "price_coverage_pct", "invented_prices")
    docs = [{"file": d["file"], "rows_extracted": d["rows_extracted"], "products_found": d["products_found"],
             "reference_products": d["reference_products"], "misses": d["misses"],
             "price_coverage": {k: v for k, v in (d.get("price_coverage") or {}).items() if k != "uncovered_pages"}}
            for d in score["documents"]]
    return {**{k: score.get(k) for k in keep}, "documents": docs}


def _print(name: str, score: dict, held_out: bool, show: bool, rows_by_file: dict, profiles: dict) -> None:
    m = score["micro"]
    print(f"\n== {name}: micro P {m['precision']} R {m['recall']} F1 {m['f1']} | found "
          f"{score['products_found']}/{score['reference_products']} | core F1 {score['micro_core']['f1']} | misses {score['misses']} | "
          f"price-page coverage {score['price_coverage_pct']}% | invented prices {score['invented_prices']}")
    print("   " + "  ".join(f"{f}:{v['f1']}" for f, v in score["per_field"].items()))
    for d in score["documents"]:
        cov = d.get("price_coverage") or {}
        print(f"   {d['file']}: rows {d['rows_extracted']}, found {d['products_found']}/{d['reference_products']}, "
              f"misses {d['misses']}, coverage {cov.get('covered')}/{cov.get('price_pages')}")
        if held_out or not show:
            continue
        print(f"     profile: {profiles.get(d['file'])}")
        for p in d["products"]:
            bad = {f: x for f, x in p["fields"].items() if x["outcome"] not in ("tp", "skip")}
            if p["rows"] == 0 or bad:
                print(f"     - {p['name']}: rows {p['rows']} {p.get('miss', '')} {json.dumps(bad, ensure_ascii=False)[:400]}")
        ents = d["spurious_entities"]
        print(f"     other entities ({len(ents)}): {ents[:40]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sets", nargs="+", choices=list(SETS), default=["tuning", "extraction"])
    ap.add_argument("--files", nargs="+", help="only these file names")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--reparse", action="store_true", help="ignore the cached parses")
    ap.add_argument("--max-unit-tokens", type=int, help="override EXTRACTION_MAX_UNIT_TOKENS")
    ap.add_argument("--judge", action="store_true", help="LLM judge for advantages/disadvantages")
    ap.add_argument("--show", action="store_true", help="print misses and other entities (never for validation)")
    args = ap.parse_args()
    os.environ["DATA_DIR"] = str(LAB_DIR)  # the lab's own database, caches and Chroma
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "eval"))
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
