"""ArgosAI evaluation: six metrics, measured on the real application code.

Metrics (see the report for the exact definitions):
  1. Document processing     share of documents processed to `ready`, per format/difficulty, time, cost
  2. Information extraction  field-level precision / recall / F1 (brand, product, code, price, currency,
                             advantages, disadvantages) against eval/ground_truth.json: notebook B
                             (complete reference), the tuning set and the frozen held-out set
  3. Query routing           routing accuracy (strict and lenient) + confusion matrix
  4. SQL generation          execution accuracy: the generated SQL and a gold SQL are run on the same
                             reference table and their results compared
  5. Performance             end-to-end latency (mean / p50 / p95) per question and per stage
  6. Consistency             every question is asked `--repeats` times; share with identical
                             route, retrieval and SQL result

Rules kept from the application:
  - two notebooks, 10 sources each (the app limit): A = eval/pdf-files/ (chat questions),
    B = eval/extraction-files/ (product documents for extraction and SQL);
  - documents go through the real upload → queue worker → pipeline; questions go through the real
    ChatOrchestrator (router → SQL / vector search → synthesizer). Nothing is faked.
  - everything runs in its own data folder (DATA_DIR = data/eval_runs/<time>/): the app's database
    and Chroma are not touched.

Uses the paid OpenAI API (OPENAI_API_KEY from .env).

Usage:
    python eval/run_eval.py                       # everything, 3 repeats
    python eval/run_eval.py --repeats 1           # quicker: no consistency measure
    python eval/run_eval.py --smoke               # 2 documents per notebook, 4 questions per set
    python eval/run_eval.py --no-judge            # skip the LLM judge for advantages/disadvantages
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "eval"
CORPUS_A = EVAL_DIR / "pdf-files"
CORPUS_B = EVAL_DIR / "extraction-files"
CORPUS_T = EVAL_DIR / "tuning-files"  # extraction only; inspected while tuning the prompt
CORPUS_V = EVAL_DIR / "validation-files"  # held-out, frozen: extraction only, aggregate scores only
RUNS_DIR = ROOT / "data" / "eval_runs"
RESULTS_DIR = EVAL_DIR / "results"

EVAL_USER = {"sub": "eval-user", "email": "eval@argos.local", "name": "Evaluation"}
FINAL_STAGES = {"ready", "failed", "cancelled"}
ROUTES = ["sql", "vector", "both", "none"]


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def pct(n: int, d: int) -> float | None:
    return round(100 * n / d, 1) if d else None


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": None if p is None else round(p, 3),
            "recall": None if r is None else round(r, 3),
            "f1": None if f1 is None else round(f1, 3)}


def quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    k = (len(v) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(v) - 1)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 1)


def latency_summary(values_ms: list[float]) -> dict:
    return {"n": len(values_ms),
            "mean_ms": round(statistics.mean(values_ms), 1) if values_ms else None,
            "p50_ms": quantile(values_ms, 0.5), "p95_ms": quantile(values_ms, 0.95),
            "max_ms": round(max(values_ms), 1) if values_ms else None}


def price_equal(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= max(0.01, abs(float(b)) * 0.005)


# --------------------------------------------------------------------------- #
# 1. Document processing (upload through the real services and wait for the worker)
# --------------------------------------------------------------------------- #
class LocalFile:
    """A file on disk in the shape the services accept (IncomingFile)."""

    def __init__(self, path: Path) -> None:
        self.filename = path.name
        self._data = path.read_bytes()
        self._pos = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk, self._pos = self._data[self._pos:], len(self._data)
        else:
            chunk = self._data[self._pos:self._pos + size]
            self._pos += len(chunk)
        return chunk


async def ingest(state, user, path: Path, timeout_s: float = 2400) -> dict:
    lib = state.library_service
    t0 = time.perf_counter()
    [res] = await lib.upload_documents(user, [LocalFile(path)])
    if res.status == "similar":
        # The documents of a set are distinct products: keep them as separate documents.
        res = await lib.resolve_pending(user, res.pending_id, "separate")
    if res.status == "rejected":
        return {"file": path.name, "stage": "rejected", "error": f"{res.error_code}: {res.error_message}",
                "seconds": 0.0}
    while True:
        v = lib.get_version(res.version_id)
        if v.stage in FINAL_STAGES or time.perf_counter() - t0 > timeout_s:
            break
        await asyncio.sleep(1)
    return {
        "file": path.name, "document_id": v.document_id, "version_id": v.id, "stage": v.stage,
        "error": v.error, "pages": v.page_count, "size_kb": round((v.size_bytes or 0) / 1024),
        "vision_failed": v.vision_failed, "reused": res.status == "existing",
        "chunks": state.vector_store.count_version(v.id),
        "seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------- #
# 2. Extraction: entity-level, field-level P / R / F1
# --------------------------------------------------------------------------- #
def _identity(row: dict) -> str:
    return norm(row.get("brand_name")) + norm(row.get("product_name")) + norm(row.get("model_code"))


def _matches(ref: dict, row: dict) -> bool:
    """A row names a reference product by its model/part number when both have one, else by name."""
    code = norm(row.get("model_code"))
    if ref.get("code") and code:
        return code == norm(ref["code"])
    key = _identity(row)
    return all(norm(t) in key for t in ref["match"]) and not any(norm(t) in key for t in ref.get("exclude", []))


def group_rows(refs: list[dict], rows: list[dict]) -> tuple[list[list[dict]], list[list[dict]]]:
    """Assign every extracted row to the reference product it names (rows of one product, one per
    document section, are merged). Rows that name no reference product are grouped by name as
    spurious entities."""
    per_ref: list[list[dict]] = [[] for _ in refs]
    spurious: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        hits = [i for i, ref in enumerate(refs) if _matches(ref, row)]
        if hits:
            # most specific reference wins (more tokens matched)
            best = max(hits, key=lambda i: len(refs[i]["match"]))
            per_ref[best].append(row)
        else:
            spurious[norm(row.get("product_name")) + "|" + norm(row.get("model_code"))].append(row)
    return per_ref, list(spurious.values())


def miss_reason(ref: dict, spurious: list[list[dict]]) -> str:
    """Why a reference product has no rows: extracted under a name/code the reference does not
    recognise (same price, or the name tokens without the identity), or not extracted at all."""
    prices = [p for p in ref.get("price", []) if p is not None]
    for group in spurious:
        if prices and any(price_equal(r.get("price"), p) for r in group for p in prices if r.get("price") is not None):
            return "extracted_unidentified_same_price"
    for group in spurious:
        key = _identity(group[0])
        if all(norm(t) in key for t in ref["product_must_contain"]):
            return "extracted_unidentified_same_name"
    return "not_extracted"


PRICE_TEXT = re.compile(r"(\$|USD|CAD|IDR|Rp\.?|€|£)\s?\d", re.IGNORECASE)


def price_pages(path: Path) -> set[int]:
    """Pages whose text layer shows a price (a currency sign or code next to a number)."""
    import pypdfium2

    pdf = pypdfium2.PdfDocument(str(path))
    try:
        return {i + 1 for i in range(len(pdf)) if PRICE_TEXT.search(pdf[i].get_textpage().get_text_range())}
    finally:
        pdf.close()


def price_coverage(path: Path, rows: list[dict]) -> dict:
    """Ground-truth-free completeness signal: share of the pages that show prices on which at least one
    priced row was extracted (a row carries the first page of its section, so this is approximate)."""
    pages = price_pages(path)
    covered = {r.get("page_number") for r in rows if r.get("price") is not None} & pages
    return {"price_pages": len(pages), "covered": len(covered), "pct": pct(len(covered), len(pages)),
            "uncovered_pages": sorted(pages - covered)}


FEATURE_FIELDS = ("brand_name", "product_name", "model_code", "price", "price_currency",
                  "advantages", "disadvantages", "page_number")


def feature_rows(conn: sqlite3.Connection, version_id: str | None) -> list[dict]:
    """The extracted rows of one document version, as dicts of FEATURE_FIELDS."""
    if not version_id:
        return []
    cur = conn.execute(f"SELECT {', '.join(FEATURE_FIELDS)} FROM features WHERE version_id = ?", (version_id,))
    return [dict(zip(FEATURE_FIELDS, r)) for r in cur]


def _first(rows: list[dict], field: str):
    """The most frequent non-empty value of `field` among the merged rows of one product."""
    values = [r.get(field) for r in rows if r.get(field) not in (None, "")]
    if not values:
        return None
    return json.loads(Counter(json.dumps(v) for v in values).most_common(1)[0][0])


def _joined(rows: list[dict], field: str) -> str | None:
    parts = list(dict.fromkeys(str(r[field]).strip() for r in rows if r.get(field)))
    return " | ".join(parts) or None


JUDGE_PROMPT = """You are grading an information-extraction system.
Product: {product}
Field: {field} (explicit {kind} facts about this product stated in the source document)
Reference key facts from the document:
{points}
Extracted value:
{prediction}

Answer "match" if the extracted value states at least one of the reference key facts (wording may
differ, any language) and contradicts none of them. Otherwise answer "no_match".
Reply only with JSON: {{"verdict": "match" | "no_match", "reason": "<one short sentence>"}}"""


async def judge_free_text(llm, product: str, field: str, points: list[str], prediction: str) -> tuple[bool, str]:
    prompt = JUDGE_PROMPT.format(
        product=product, field=field, kind="positive" if field == "advantages" else "negative",
        points="\n".join(f"- {p}" for p in points), prediction=prediction[:3000])
    raw = await llm.ainvoke(prompt=prompt, system=None)
    try:
        data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        return data.get("verdict") == "match", str(data.get("reason", ""))
    except (json.JSONDecodeError, AttributeError):
        return False, f"unparseable judge output: {raw[:120]}"


FIELDS = ["brand", "product", "code", "price", "currency", "advantages", "disadvantages"]


async def score_extraction(gt_docs: list[dict], rows_by_file: dict[str, list[dict]], judge,
                           paths: dict[str, Path] | None = None) -> dict:
    fields = FIELDS
    counts = {f: [0, 0, 0] for f in fields}  # tp, fp, fn
    details = []
    for doc in gt_docs:
        refs = doc["products"]
        rows = rows_by_file.get(doc["file"], [])
        per_ref, spurious = group_rows(refs, rows)
        doc_detail = {"file": doc["file"], "rows_extracted": len(rows), "reference_products": len(refs),
                      "products_found": sum(1 for g in per_ref if g), "spurious_entities": [], "products": [],
                      "misses": Counter()}
        if paths and doc["file"] in paths:
            doc_detail["price_coverage"] = price_coverage(paths[doc["file"]], rows)

        for ref, group in zip(refs, per_ref):
            pd = {"name": ref["name"], "rows": len(group), "fields": {}}
            if not group:
                pd["miss"] = miss_reason(ref, spurious)
                doc_detail["misses"][pd["miss"]] += 1
            pred = {
                "brand": _first(group, "brand_name"), "product": _first(group, "product_name"),
                "code": _first(group, "model_code"),
                "price": _first(group, "price"), "currency": _first(group, "price_currency"),
                "advantages": _joined(group, "advantages"), "disadvantages": _joined(group, "disadvantages"),
            }
            # exact fields
            for f in ("brand", "product", "code", "price", "currency"):
                if f == "code" and not ref.get("code"):
                    continue  # the reference product has no model/part number
                accepted = ref[{"brand": "brand", "product": "product_must_contain"}.get(f, f)]
                p = pred[f]
                if f == "product":
                    # product_name holds line + model + variant without the brand; a part number may sit
                    # in model_code instead of the name (the reference lists the tokens of either)
                    ident = norm(p) + norm(pred["code"])
                    ok = p is not None and all(norm(t) in ident for t in accepted)
                    required = True
                elif f == "code":
                    ok = p is not None and norm(p) == norm(accepted)
                    required = True
                elif f == "price":
                    ok = any(price_equal(p, a) for a in accepted if a is not None) if p is not None else False
                    required = None not in accepted
                else:
                    ok = p is not None and norm(p) in {norm(a) for a in accepted if a is not None}
                    required = None not in accepted
                if f == "code" and p is None and pred["product"] and norm(accepted) in norm(pred["product"]):
                    outcome = "skip"  # the model name is the code ("KMU-100"): it stays in product_name
                elif p is None:
                    outcome = "fn" if required else "skip"
                else:
                    outcome = "tp" if ok else "fp+fn" if required else "fp"
                _count(counts[f], outcome)
                pd["fields"][f] = {"predicted": p, "outcome": outcome}
            # free-text fields
            for f in ("advantages", "disadvantages"):
                spec, p = ref[f], pred[f]
                if p is None:
                    outcome = "fn" if spec["points"] and not spec["optional"] else "skip"
                    reason = ""
                elif not spec["points"]:
                    outcome, reason = ("fp", "the document states none") if not spec["optional"] else ("skip", "optional")
                elif judge is None:
                    outcome, reason = "unjudged", ""
                else:
                    ok, reason = await judge_free_text(judge, ref["name"], f, spec["points"], p)
                    outcome = "tp" if ok else ("fp" if spec["optional"] else "fp+fn")
                if outcome != "unjudged":
                    _count(counts[f], outcome)
                pd["fields"][f] = {"predicted": p, "outcome": outcome, "reason": reason}
            doc_detail["products"].append(pd)

        for group in spurious:
            name = _first(group, "product_name")
            doc_detail["spurious_entities"].append(name)
            if doc.get("expect_no_price"):
                # a document without customer prices: any price on any row is invented
                doc_detail["invented_prices"] = doc_detail.get("invented_prices", 0) + sum(
                    1 for r in group if r.get("price") is not None)
            if doc.get("complete") is False:
                continue  # the reference is a sample: other products may be real, not errors
            for f, col in (("brand", "brand_name"), ("product", "product_name"), ("code", "model_code"),
                           ("price", "price"), ("currency", "price_currency"), ("advantages", "advantages"),
                           ("disadvantages", "disadvantages")):
                if any(r.get(col) not in (None, "") for r in group):
                    counts[f][1] += 1
        doc_detail["misses"] = dict(doc_detail["misses"])
        details.append(doc_detail)

    per_field = {f: prf(*counts[f]) for f in fields}
    micro = prf(*(sum(counts[f][i] for f in fields) for i in range(3)))
    f1s = [m["f1"] for m in per_field.values() if m["f1"] is not None]
    misses = Counter()
    for d in details:
        misses.update(d["misses"])
    cov = [d["price_coverage"] for d in details if d.get("price_coverage", {}).get("price_pages")]
    core = ("brand", "product", "price", "currency")  # comparable with runs before the code field
    return {"per_field": per_field, "micro": micro,
            "micro_core": prf(*(sum(counts[f][i] for f in core) for i in range(3))),
            "macro_f1": round(statistics.mean(f1s), 3) if f1s else None,
            "products_found": sum(d["products_found"] for d in details),
            "reference_products": sum(d["reference_products"] for d in details),
            "misses": dict(misses),
            "price_coverage_pct": pct(sum(c["covered"] for c in cov), sum(c["price_pages"] for c in cov)),
            "invented_prices": sum(d.get("invented_prices", 0) for d in details),
            "documents": details}


def _count(c: list[int], outcome: str) -> None:
    if outcome == "tp":
        c[0] += 1
    elif outcome == "fp":
        c[1] += 1
    elif outcome == "fn":
        c[2] += 1
    elif outcome == "fp+fn":
        c[1] += 1
        c[2] += 1


# --------------------------------------------------------------------------- #
# 3 / 5 / 6. Routing, latency and consistency (real chat flow in notebook A)
# --------------------------------------------------------------------------- #
def _retrieval_signature(trace: dict) -> str:
    """What was retrieved: SQL status/row count and the pages of the chunks. Distances are left out:
    embeddings vary in the last decimals between identical calls, which is not a different retrieval."""
    sql = trace.get("sql") or {}
    pages = sorted(str(c.get("page")) for c in (trace.get("chunks") or []))
    return json.dumps({"sql_rows": sql.get("row_count"), "sql_status": sql.get("status"), "chunk_pages": pages})


def _strip_distances(signature: str) -> str:
    """Rescoring an older report: rebuild its retrieval signature without distances."""
    s = json.loads(signature)
    pages = sorted(str(c[0]) for c in s.get("chunks", []))
    return json.dumps({"sql_rows": s.get("sql_rows"), "sql_status": s.get("sql_status"), "chunk_pages": pages})


async def ask(state, user, notebook_id: str, question: dict) -> dict:
    orch = state.chat_orchestrator
    conversation_id = None
    for earlier in question.get("history", []):
        reply = await orch.send(user, notebook_id, earlier, conversation_id)
        conversation_id = reply.conversation_id
    t0 = time.perf_counter()
    try:
        reply = await orch.send(user, notebook_id, question["q"], conversation_id)
    except Exception as e:  # noqa: BLE001 — a failed question is a result, not a crash
        return {"id": question["id"], "error": f"{type(e).__name__}: {e}"[:300],
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)}
    latency = (time.perf_counter() - t0) * 1000
    r = reply.result
    trace = r.trace or {}
    return {
        "id": question["id"], "route": r.route, "router_reasoning": r.router_reasoning,
        "latency_ms": round(latency, 1),
        "stages_ms": {k: (trace.get(k) or {}).get("duration_ms") for k in ("router", "sql", "vector", "synthesizer")},
        "message_id": reply.user_message.id, "retrieval": _retrieval_signature(trace),
        "sql_query": (trace.get("sql") or {}).get("query"), "answer": r.answer,
        "issues": [i.to_dict() for i in r.issues],
    }


def score_routing(questions: list[dict], runs: list[list[dict]]) -> dict:
    by_id = {q["id"]: q for q in questions}
    first = runs[0]
    strict = lenient = answered = 0
    confusion = {g: Counter() for g in ROUTES}
    misses = []
    for res in first:
        q = by_id[res["id"]]
        if "route" not in res:
            misses.append({"id": q["id"], "expected": q["route"], "got": "ERROR", "detail": res.get("error")})
            continue
        answered += 1
        confusion[q["route"]][res["route"]] += 1
        if res["route"] == q["route"]:
            strict += 1
            lenient += 1
        elif res["route"] in q.get("also", []):
            lenient += 1
            misses.append({"id": q["id"], "expected": q["route"], "got": res["route"], "accepted_as": "also"})
        else:
            misses.append({"id": q["id"], "expected": q["route"], "got": res["route"],
                           "reasoning": res.get("router_reasoning")})
    per_class = {}
    for g in ROUTES:
        tp = confusion[g][g]
        fp = sum(confusion[o][g] for o in ROUTES if o != g)
        fn = sum(confusion[g].values()) - tp
        per_class[g] = prf(tp, fp, fn)
    return {"questions": len(first), "strict_accuracy_pct": pct(strict, len(first)),
            "lenient_accuracy_pct": pct(lenient, len(first)),
            "per_route": per_class,
            "confusion": {g: dict(confusion[g]) for g in ROUTES}, "misses": misses}


def score_consistency(runs: list[list[dict]], key_fields: tuple[str, ...]) -> dict | None:
    if len(runs) < 2:
        return None
    per_q: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        for res in run:
            per_q[res["id"]].append(res)
    out = {}
    for field in key_fields:
        same = sum(1 for results in per_q.values() if len({json.dumps(r.get(field), default=str) for r in results}) == 1)
        out[f"{field}_identical_pct"] = pct(same, len(per_q))
    all_same = sum(1 for results in per_q.values()
                   if all(len({json.dumps(r.get(f), default=str) for r in results}) == 1 for f in key_fields))
    out["all_identical_pct"] = pct(all_same, len(per_q))
    out["repeats"] = len(runs)
    out["questions"] = len(per_q)
    return out


# --------------------------------------------------------------------------- #
# 4. SQL execution accuracy on the reference table
# --------------------------------------------------------------------------- #
REF_BRAND = {
    "id_kia_pricelist_jakarta.pdf": "Kia", "id_cimb_riplay_mc_gold.pdf": "CIMB Niaga",
    "id_cimb_riplay_mc_platinum.pdf": "CIMB Niaga", "id_cimb_riplay_mc_world.pdf": "CIMB Niaga",
    "id_cimb_riplay_octo.pdf": "CIMB Niaga", "id_mega_riplay_gold.pdf": "Bank Mega",
    "id_icbc_creditcard.pdf": "ICBC", "en_lenovo_t14_gen5_intel.pdf": "Lenovo",
    "en_lenovo_t14s_gen5.pdf": "Lenovo", "en_hp_probook4_g1i.pdf": "HP",
}


def build_reference_db(path: Path, gt_docs: list[dict]) -> list[str]:
    """`features` table with one row per reference product (the value a perfect extraction yields)."""
    from app.services.nl2sql.executor import FEATURE_COLUMNS

    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(f"CREATE TABLE features ({', '.join(f'{n} {k}' for n, k in FEATURE_COLUMNS)})")
    version_ids = []
    for doc in gt_docs:
        vid = "ref-" + doc["file"].removesuffix(".pdf")
        version_ids.append(vid)
        for ref in doc["products"]:
            price = next((p for p in ref["price"] if p is not None), None)
            currency = next((c for c in ref["currency"] if c is not None), None) if price is not None else None
            conn.execute(
                "INSERT INTO features (version_id, page_number, section_heading, brand_name, product_name, "
                "price, price_currency, advantages, disadvantages) VALUES (?,?,?,?,?,?,?,?,?)",
                (vid, 1, None, REF_BRAND[doc["file"]], ref["name"], price, currency,
                 "; ".join(ref["advantages"]["points"]) or None, "; ".join(ref["disadvantages"]["points"]) or None))
    conn.commit()
    conn.close()
    return version_ids


def _cell(v) -> str:
    if isinstance(v, (int, float)):
        return f"{round(float(v), 2):.2f}"
    return norm(v)


def compare_results(gold: list[dict], got: list[dict], answer_columns: list[str], ordered: bool) -> tuple[bool, str]:
    """Execution match: every gold answer column must appear in the generated result with the same
    values (by value, whatever the column is called); same number of rows; order checked when the
    question asks for one. Extra columns in the generated result are allowed."""
    if len(gold) != len(got):
        return False, f"{len(got)} rows, expected {len(gold)}"
    if not gold:
        return True, "both empty"
    got_cols = list(got[0].keys())
    for col in answer_columns:
        want = [_cell(r[col]) for r in gold]
        found = False
        for gc in got_cols:
            have = [_cell(r[gc]) for r in got]
            if (have == want) if ordered else (sorted(have) == sorted(want)):
                found = True
                break
        if not found:
            return False, f"no generated column matches gold column '{col}'" + (" in order" if ordered else "")
    return True, "match"


async def run_sql_eval(nl2sql_llm, ref_db: Path, version_ids: list[str], questions: list[dict], repeats: int) -> dict:
    from app.services.nl2sql.executor import execute_scoped_sql
    from app.services.nl2sql.service import NL2SQLService

    svc = NL2SQLService(nl2sql_llm, ref_db, exec_timeout=5.0)
    runs: list[list[dict]] = []
    for rep in range(repeats):
        run = []
        for q in questions:
            gold, _ = execute_scoped_sql(q["gold_sql"], ref_db, version_ids, 5.0, 500)
            t0 = time.perf_counter()
            res = await svc.process_query(q["q"], version_ids)
            ms = (time.perf_counter() - t0) * 1000
            ok, why = (compare_results(gold, res.raw_data, q["answer_columns"], q["ordered"])
                       if res.status != "error" else (False, f"error {res.error_code}"))
            run.append({"id": q["id"], "correct": ok, "why": why, "status": res.status, "sql": res.sql_query,
                        "result": json.dumps(sorted(json.dumps(r, sort_keys=True, default=str) for r in res.raw_data)),
                        "rows": res.row_count, "gold_rows": len(gold), "latency_ms": round(ms, 1)})
        runs.append(run)
        print(f"  [sql] run {rep + 1}/{repeats}: {sum(r['correct'] for r in run)}/{len(run)} correct", flush=True)
    return summarize_sql(runs)


def summarize_sql(runs: list[list[dict]]) -> dict:
    first = runs[0]
    for run in runs:
        for r in run:
            # The answer: a correct result is the gold answer; a wrong one is its raw rows. Extra columns
            # such as version_id/page_number do not make two correct answers different.
            r["answer"] = "correct" if r["correct"] else r["result"]
    return {
        "questions": len(first),
        "execution_accuracy_pct": pct(sum(r["correct"] for r in first), len(first)),
        "execution_accuracy_all_runs_pct": pct(sum(r["correct"] for run in runs for r in run), len(first) * len(runs)),
        "correct_in_every_run_pct": pct(sum(all(run[i]["correct"] for run in runs) for i in range(len(first))), len(first)),
        "executable_pct": pct(sum(r["status"] != "error" for r in first), len(first)),
        "latency": latency_summary([r["latency_ms"] for run in runs for r in run]),
        "consistency": score_consistency(runs, ("sql", "answer")),
        "results": first,
        "runs": runs,
    }


# --------------------------------------------------------------------------- #
# Main run
# --------------------------------------------------------------------------- #
async def run(args, gt: dict, qs: dict, run_dir: Path) -> dict:
    from fastapi import FastAPI

    from app.bootstrap import lifespan
    from app.core.database import DB_PATH
    from app.services.user.model import CurrentUser
    from app.tools.factory import build_llm

    files_a = sorted(CORPUS_A.glob("*.pdf"))
    files_b = sorted(CORPUS_B.glob("*.pdf"))
    files_t = sorted(CORPUS_T.glob("*.pdf")) if not args.no_validation else []
    files_v = sorted(CORPUS_V.glob("*.pdf")) if not args.no_validation else []
    routing_q, sql_q = qs["routing"], qs["sql"]
    if args.smoke:
        files_a, files_b, routing_q, sql_q = files_a[:2], files_b[:2], routing_q[:4], sql_q[:4]

    report: dict = {"started": datetime.now().isoformat(timespec="seconds"), "repeats": args.repeats}
    app = FastAPI()
    async with lifespan(app):
        st = app.state
        u = st.user_repo.upsert_on_login(EVAL_USER["sub"], EVAL_USER["email"], EVAL_USER["name"], None)
        user = CurrentUser(id=u.id, email=u.email, name=u.name or "", given_name="", picture="", is_admin=False)

        # 1. document processing
        processed = {}
        for corpus, files in (("A", files_a), ("B", files_b), ("T", files_t), ("V", files_v)):
            for path in files:
                if path.name in processed:
                    processed[path.name]["corpus"] += corpus
                    continue
                print(f"[ingest] {corpus} {path.name} ...", flush=True)
                info = await ingest(st, user, path)
                info["corpus"] = corpus
                processed[path.name] = info
                print(f"         {info['stage']} in {info['seconds']} s, {info.get('chunks')} chunks", flush=True)

        def notebook(title: str, files: list[Path]) -> str:
            nb = st.notebook_service.create(user, title)
            doc_ids = [processed[p.name]["document_id"] for p in files
                       if processed[p.name].get("stage") == "ready"]
            st.notebook_service.add_from_library(user, nb.id, doc_ids)  # enforces the 10-source limit
            return nb.id

        nb_a = notebook("Eval A — questions", files_a)
        nb_b = notebook("Eval B — product documents", files_b)
        report["notebooks"] = {"A": len(st.notebook_service.active_sources(user, nb_a)),
                               "B": len(st.notebook_service.active_sources(user, nb_b))}

        # 2. extraction rows of notebook B, the tuning set and the held-out set
        with sqlite3.connect(DB_PATH) as conn:
            rows_by_file = {path.name: feature_rows(conn, processed[path.name].get("version_id"))
                            for path in files_b + files_t + files_v}

        # 3/5/6. routing, latency, consistency in notebook A
        routing_runs = []
        for rep in range(args.repeats):
            run_results = []
            for q in routing_q:
                run_results.append(await ask(st, user, nb_a, q))
            routing_runs.append(run_results)
            ok = sum(1 for r, q in zip(run_results, routing_q) if r.get("route") == q["route"])
            print(f"  [routing] run {rep + 1}/{args.repeats}: {ok}/{len(routing_q)} strict", flush=True)

        # 4. SQL execution accuracy on the reference table — always the full reference (it does not
        #    depend on what was ingested, and a smaller table would make some questions trivially empty)
        ref_db = run_dir / "reference_features.db"
        version_ids = build_reference_db(ref_db, gt["extraction"]["documents"])
        gt_b = [d for d in gt["extraction"]["documents"] if d["file"] in {p.name for p in files_b}]
        report["sql"] = await run_sql_eval(st.nl2sql_service.llm, ref_db, version_ids, sql_q, args.repeats)

        # extraction scoring (LLM judge for free-text fields)
        judge = None if args.no_judge else build_llm("router", 0.0)
        paths = {p.name: p for p in files_b + files_t + files_v}
        report["extraction"] = await score_extraction(gt_b, rows_by_file, judge, paths)
        for key, files in (("tuning", files_t), ("validation", files_v)):
            if files:
                docs = [d for d in gt[key]["documents"] if d["file"] in {p.name for p in files}]
                report[key] = await score_extraction(docs, rows_by_file, judge, paths)

    # after shutdown the AI-call recorder has written every row: costs per document / question
    with sqlite3.connect(DB_PATH) as conn:
        calls = [dict(zip(("purpose", "model", "in", "out", "version_id", "message_id"), r)) for r in conn.execute(
            "SELECT purpose, model, input_tokens, output_tokens, version_id, message_id FROM llm_calls")]
    report["documents"] = summarize_documents(processed, calls)
    report["routing"] = score_routing(routing_q, routing_runs)
    report["routing"]["consistency"] = score_consistency(routing_runs, ("route", "retrieval"))
    report["performance"] = summarize_latency(routing_runs, calls)
    report["routing_runs"] = routing_runs
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    return report


def _cost(call: dict) -> float:
    from app.core.observability.telemetry.pricing import token_cost

    c = token_cost(call["model"], call["in"], call["out"])
    return c["total"] if c else 0.0


def summarize_documents(processed: dict, calls: list[dict]) -> dict:
    by_version = defaultdict(list)
    for c in calls:
        if c["version_id"]:
            by_version[c["version_id"]].append(c)
    docs = []
    for info in processed.values():
        vc = by_version.get(info.get("version_id"), [])
        info["ai_calls"] = len(vc)
        info["vision_calls"] = sum(1 for c in vc if c["purpose"] == "vision")
        info["cost_usd"] = round(sum(_cost(c) for c in vc), 4)
        docs.append(info)
    ready = [d for d in docs if d["stage"] == "ready"]
    return {"total": len(docs), "ready": len(ready), "success_rate_pct": pct(len(ready), len(docs)),
            "pages": sum(d.get("pages") or 0 for d in docs),
            "seconds_total": round(sum(d["seconds"] for d in docs), 1),
            "seconds_per_page": round(sum(d["seconds"] for d in ready) / max(1, sum(d.get("pages") or 0 for d in ready)), 2),
            "cost_usd_total": round(sum(d["cost_usd"] for d in docs), 4), "items": docs}


def summarize_latency(runs: list[list[dict]], calls: list[dict]) -> dict:
    flat = [r for run in runs for r in run if "latency_ms" in r and "route" in r]
    by_route = defaultdict(list)
    for r in flat:
        by_route[r["route"]].append(r["latency_ms"])
    stages = defaultdict(list)
    for r in flat:
        for k, v in (r.get("stages_ms") or {}).items():
            if v is not None:
                stages[k].append(v)
    msg_ids = {r["message_id"] for r in flat}
    q_calls = [c for c in calls if c["message_id"] in msg_ids]
    return {"end_to_end": latency_summary([r["latency_ms"] for r in flat]),
            "by_route": {k: latency_summary(v) for k, v in by_route.items()},
            "by_stage": {k: latency_summary(v) for k, v in stages.items()},
            "cost_usd_per_question": round(sum(_cost(c) for c in q_calls) / max(1, len(flat)), 5),
            "tokens_per_question": round(sum((c["in"] or 0) + (c["out"] or 0) for c in q_calls) / max(1, len(flat)))}


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #
def fmt(v, suffix=""):
    return "–" if v is None else f"{v}{suffix}"


def markdown(r: dict) -> str:
    d, e, ro, s, p = r["documents"], r["extraction"], r["routing"], r["sql"], r["performance"]
    L = [f"# ArgosAI evaluation — {r['started']}", "",
         f"Repeats per question: {r['repeats']}. Notebook A: {r['notebooks']['A']} sources, "
         f"notebook B: {r['notebooks']['B']} sources (limit 10).", "",
         "## Summary", "", "| Area | Metric | Result |", "|---|---|---|",
         f"| Document processing | documents processed to `ready` | {d['ready']}/{d['total']} ({fmt(d['success_rate_pct'], '%')}) |",
         f"| Information extraction | field-level micro F1 (macro F1) | {fmt(e['micro']['f1'])} ({fmt(e['macro_f1'])}) |"]
    for key, label in (("tuning", "tuning set"), ("validation", "held-out set")):
        x = r.get(key)
        if x:
            L.append(f"| Information extraction | {label}: micro F1 / products found | "
                     f"{fmt(x['micro']['f1'])} / {x['products_found']}/{x['reference_products']} |")
    L += [
         f"| Query routing | accuracy, strict / lenient | {fmt(ro['strict_accuracy_pct'], '%')} / {fmt(ro['lenient_accuracy_pct'], '%')} |",
         f"| SQL generation | execution accuracy (first run / all runs) | {fmt(s['execution_accuracy_pct'], '%')} / {fmt(s['execution_accuracy_all_runs_pct'], '%')} |",
         f"| Performance | end-to-end latency mean / p50 / p95 | {fmt(p['end_to_end']['mean_ms'], ' ms')} / {fmt(p['end_to_end']['p50_ms'], ' ms')} / {fmt(p['end_to_end']['p95_ms'], ' ms')} |"]
    rc, sc = ro.get("consistency"), s.get("consistency")
    if rc:
        L.append(f"| Consistency | same route / same retrieval / same SQL answer over {rc['repeats']} runs | "
                 f"{fmt(rc['route_identical_pct'], '%')} / {fmt(rc['retrieval_identical_pct'], '%')} / {fmt(sc['answer_identical_pct'], '%')} |")
    L += ["", "## 1. Document processing", "",
          f"{d['pages']} pages in {d['seconds_total']} s ({d['seconds_per_page']} s/page), AI cost ${d['cost_usd_total']}.", "",
          "| File | Set | Stage | Pages | Chunks | Vision calls | Seconds | Cost (USD) |", "|---|---|---|---|---|---|---|---|"]
    for it in d["items"]:
        L.append(f"| {it['file']} | {it['corpus']} | {it['stage']} | {fmt(it.get('pages'))} | {fmt(it.get('chunks'))} | "
                 f"{it.get('vision_calls', 0)} | {it['seconds']} | {it.get('cost_usd', 0)} |")
    L += ["", "## 2. Information extraction (notebook B, entity level)", "",
          "| Field | Precision | Recall | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    for f, m in e["per_field"].items():
        L.append(f"| {f} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | {m['tp']} | {m['fp']} | {m['fn']} |")
    m = e["micro"]
    L.append(f"| **micro** | {fmt(m['precision'])} | {fmt(m['recall'])} | **{fmt(m['f1'])}** | {m['tp']} | {m['fp']} | {m['fn']} |")
    L += ["", "| Document | Rows extracted | Products found | Spurious entities |", "|---|---|---|---|"]
    for doc in e["documents"]:
        L.append(f"| {doc['file']} | {doc['rows_extracted']} | {doc['products_found']}/{doc['reference_products']} | "
                 f"{', '.join(map(str, doc['spurious_entities'])) or '–'} |")
    for key, title, show_entities in (
            ("tuning", "Tuning set (eval/tuning-files, inspected while tuning; sample reference)", True),
            ("validation", "Held-out validation (eval/validation-files, frozen; sample reference except Biznet)", False)):
        v = r.get(key)
        if v:
            L += markdown_extraction_set(v, title, show_entities)
    L += ["", "## 3. Query routing (notebook A)", "",
          "| Route | Precision | Recall | F1 |", "|---|---|---|---|"]
    for g, mm in ro["per_route"].items():
        L.append(f"| {g} | {fmt(mm['precision'])} | {fmt(mm['recall'])} | {fmt(mm['f1'])} |")
    L += ["", "Confusion (rows = expected, columns = chosen):", "", "| | " + " | ".join(ROUTES) + " |", "|---" * (len(ROUTES) + 1) + "|"]
    for g in ROUTES:
        L.append(f"| {g} | " + " | ".join(str(ro["confusion"][g].get(o, 0)) for o in ROUTES) + " |")
    if ro["misses"]:
        L += ["", "Misses:", ""] + [f"- `{x['id']}`: expected {x['expected']}, got {x['got']}"
                                    + (" (allowed alternative)" if x.get("accepted_as") else "") for x in ro["misses"]]
    L += ["", "## 4. SQL generation (reference table)", "",
          f"Executable: {fmt(s['executable_pct'], '%')}. Execution accuracy: {fmt(s['execution_accuracy_pct'], '%')}.", "",
          "| Question | Correct | Detail |", "|---|---|---|"]
    for x in s["results"]:
        L.append(f"| `{x['id']}` | {'✅' if x['correct'] else '❌'} | {x['why']} |")
    L += ["", "## 5. Performance", "", "| Scope | n | Mean | p50 | p95 | Max |", "|---|---|---|---|---|---|"]
    rows = [("end-to-end", p["end_to_end"])] + [(f"route {k}", v) for k, v in p["by_route"].items()] + \
           [(f"stage {k}", v) for k, v in p["by_stage"].items()] + [("NL2SQL (reference table)", s["latency"])]
    for name, v in rows:
        L.append(f"| {name} | {v['n']} | {fmt(v['mean_ms'])} | {fmt(v['p50_ms'])} | {fmt(v['p95_ms'])} | {fmt(v['max_ms'])} |")
    L.append(f"\nAverage per question: {p['tokens_per_question']} tokens, ${p['cost_usd_per_question']}.")
    if rc:
        L += ["", "## 6. Consistency", "",
              f"Chat (notebook A, {rc['questions']} questions × {rc['repeats']}): same route {fmt(rc['route_identical_pct'], '%')}, "
              f"same retrieval {fmt(rc['retrieval_identical_pct'], '%')}, both {fmt(rc['all_identical_pct'], '%')}.",
              f"SQL (reference table, {sc['questions']} questions × {sc['repeats']}): same answer {fmt(sc['answer_identical_pct'], '%')} "
              f"(correct in every run: {fmt(s['correct_in_every_run_pct'], '%')}); same SQL text {fmt(sc['sql_identical_pct'], '%')} — "
              "the wording of the SQL may vary while the answer stays the same."]
    L += ["", "## Method", "", METHOD]
    return "\n".join(L) + "\n"


MISS_LABELS = {"not_extracted": "not extracted",
               "extracted_unidentified_same_price": "extracted, unidentified (same price)",
               "extracted_unidentified_same_name": "extracted, unidentified (name tokens)"}


def markdown_extraction_set(v: dict, title: str, show_entities: bool) -> list[str]:
    """Scores of one extraction set. Held-out sets show aggregates only: their output is not
    inspected while the prompt is tuned."""
    L = ["", f"### {title}", "",
         f"Sample products found: {v['products_found']}/{v['reference_products']}. "
         f"Pages showing prices with an extracted priced row: {fmt(v.get('price_coverage_pct'), '%')}. "
         f"Invented prices (documents without prices): {v.get('invented_prices', 0)}.", "",
         "| Field | Precision* | Recall | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|"]
    for f, m in v["per_field"].items():
        L.append(f"| {f} | {fmt(m['precision'])} | {fmt(m['recall'])} | {fmt(m['f1'])} | {m['tp']} | {m['fp']} | {m['fn']} |")
    m = v["micro"]
    L.append(f"| **micro** | {fmt(m['precision'])} | {fmt(m['recall'])} | **{fmt(m['f1'])}** | {m['tp']} | {m['fp']} | {m['fn']} |")
    L += ["", "*On a sample reference, precision counts only the sampled products' fields.", "",
          "| Document | Rows | Sample found | Price-page coverage | Misses |" + (" Other entities |" if show_entities else ""),
          "|---|---|---|---|---|" + ("---|" if show_entities else "")]
    for doc in v["documents"]:
        cov = doc.get("price_coverage") or {}
        cov_s = f"{cov['covered']}/{cov['price_pages']}" if cov.get("price_pages") else "–"
        misses = ", ".join(f"{MISS_LABELS.get(k, k)}: {n}" for k, n in doc["misses"].items()) or "–"
        line = f"| {doc['file']} | {doc['rows_extracted']} | {doc['products_found']}/{doc['reference_products']} | {cov_s} | {misses} |"
        if show_entities:
            ents = doc["spurious_entities"]
            line += " " + (", ".join(map(str, ents[:12])) + (" …" if len(ents) > 12 else "") or "–") + " |"
        L.append(line)
    return L


METHOD = """- **Document processing** — every file is uploaded through the Library service and processed by the
  real queue worker (Docling → vision → chunking/embedding → extraction). Success = the version reaches
  `ready`. Cost comes from the app's own `llm_calls` records priced with the telemetry price table.
- **Information extraction** — entity level: extracted rows naming the same product (the app stores one
  row per document section) are merged; each reference product is identified by its name tokens. For each
  field: TP = a non-empty prediction equal to an accepted reference value; FP = a non-empty wrong value, or
  any value on a spurious entity; FN = an empty or wrong prediction where the reference requires a value.
  Empty predictions where the document states nothing are true negatives and not counted. Prices match
  within ±0.5%. Advantages/disadvantages are free text: an LLM judge decides whether the prediction states
  at least one reference key fact without contradicting any (same model family as the system — a known
  bias; the judge output is kept in report.json for review). Micro F1 pools all fields; macro F1 averages
  the per-field F1. A row names a reference product by its model/part number (`model_code`) when both
  have one, otherwise by name tokens; `code` is scored where the reference has one. A sample product with
  no rows is labelled: extracted but unidentified (a row with the same price or the name tokens exists
  under another identity) or not extracted. Price-page coverage needs no reference: the share of pages
  whose text shows a price on which at least one priced row was extracted. Three extraction sets:
  notebook B (complete reference), the tuning set (inspected while the prompt was tuned) and the frozen
  held-out set (aggregate scores only; never inspected while tuning).
- **Query routing** — each question carries the label prescribed by the routing rules. Strict accuracy
  counts only that label; lenient also accepts an alternative the rules themselves allow for that wording.
  Per-route precision/recall/F1 from the confusion matrix of the first run.
- **SQL generation** — execution accuracy (as in Spider/BIRD): the app's NL2SQL service generates and runs
  SQL on a reference `features` table built from the ground truth (so extraction errors do not leak into
  this score); a hand-written gold SQL runs in the same sandbox. Correct = same number of rows and every
  gold answer column found among the generated columns with the same values (in order when the question
  asks for an order). Extra columns are allowed.
- **Performance** — wall-clock time of `ChatOrchestrator.send` per question (router, retrieval,
  synthesizer), plus the per-stage durations the engine records. Ingestion time per document is in §1.
- **Consistency** — every question is asked `repeats` times in a new conversation; reported as the share of
  questions with an identical route and identical retrieval (SQL status and row count, pages of the retrieved
  chunks) in all runs. For SQL: the share of questions whose answer is the same in every run (correct every
  time, or the same rows every time); the share with byte-identical SQL text is shown separately.
- **Brand** is required wherever the document writes it in its text; only the Kia price list (brand in
  the logo only) accepts an empty brand."""


async def rescore(args, gt: dict, qs: dict, out: Path) -> dict:
    """Recompute the scores of a finished run with the current ground truth and scoring code.

    Reuses what the run stored: its database (extracted rows) and its chat answers (routing,
    latency, consistency). The SQL stage is cheap and independent of ingestion, so it runs again.
    """
    from app.core.database import DB_PATH
    from app.tools.factory import build_llm

    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    report["rescored"] = datetime.now().isoformat(timespec="seconds")

    paths = {p.name: p for corpus in (CORPUS_B, CORPUS_T, CORPUS_V) for p in corpus.glob("*.pdf")}
    versions = {d["file"]: d.get("version_id") for d in report["documents"]["items"]}
    with sqlite3.connect(DB_PATH) as conn:
        rows_by_file = {name: feature_rows(conn, versions.get(name)) for name in paths}
    judge = None if args.no_judge else build_llm("router", 0.0)
    for key, corpus in (("extraction", CORPUS_B), ("tuning", CORPUS_T), ("validation", CORPUS_V)):
        names = {p.name for p in corpus.glob("*.pdf")} & set(versions)
        docs = [d for d in gt[key]["documents"] if d["file"] in names]
        if docs:
            report[key] = await score_extraction(docs, rows_by_file, judge, paths)

    for run in report["routing_runs"]:
        for r in run:
            if r.get("retrieval") and '"chunks"' in r["retrieval"]:
                r["retrieval"] = _strip_distances(r["retrieval"])
    report["routing"] = score_routing(qs["routing"], report["routing_runs"])
    report["routing"]["consistency"] = score_consistency(report["routing_runs"], ("route", "retrieval"))

    ref_db = Path(os.environ["DATA_DIR"]) / "reference_features.db"
    version_ids = build_reference_db(ref_db, gt["extraction"]["documents"])
    report["sql"] = await run_sql_eval(build_llm("nl2sql", 0.0), ref_db, version_ids, qs["sql"], report["repeats"])
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--smoke", action="store_true", help="2 documents per notebook, 4 questions per set")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge for free-text fields")
    ap.add_argument("--no-validation", action="store_true", help="skip the held-out extraction set")
    ap.add_argument("--rescore", metavar="RUN", help="recompute the scores of eval/results/RUN with the current "
                                                     "ground truth and scoring (SQL stage runs again)")
    args = ap.parse_args()

    gt = json.loads((EVAL_DIR / "ground_truth.json").read_text(encoding="utf-8"))
    qs = json.loads((EVAL_DIR / "questions.json").read_text(encoding="utf-8"))

    if args.rescore:
        out = RESULTS_DIR / args.rescore
        os.environ["DATA_DIR"] = str(RUNS_DIR / args.rescore)
        sys.path.insert(0, str(ROOT))
        report = asyncio.run(rescore(args, gt, qs, out))
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        (out / "report.md").write_text(markdown(report), encoding="utf-8")
        print(f"\nReport (rescored): {out / 'report.md'}")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + ("_smoke" if args.smoke else "")
    run_dir = RUNS_DIR / stamp
    run_dir.mkdir(parents=True, exist_ok=True)
    os.environ["DATA_DIR"] = str(run_dir)  # this run's database, Chroma and upload queue
    sys.path.insert(0, str(ROOT))

    report = asyncio.run(run(args, gt, qs, run_dir))
    out = RESULTS_DIR / stamp
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "report.md").write_text(markdown(report), encoding="utf-8")
    print(f"\nReport: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
