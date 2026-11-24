# ArgosAI — Evaluation Results

Benchmark of the full ArgosAI pipeline (document processing, information extraction, query
routing, NL2SQL, performance and consistency) on real competitor documents.

| | |
|---|---|
| Date | 24 November 2026 |
| Models | `gpt-6-luna` (router, NL2SQL, extraction, vision, chat), `text-embedding-3-small` |
| Repeats | every chat and SQL question asked 3 times, each in a new conversation |
| Harness | [`run_eval.py`](run_eval.py) · [`extraction_lab.py`](extraction_lab.py) · ground truth [`ground_truth.json`](ground_truth.json) · questions [`questions.json`](questions.json) |
| Raw reports | [`results/20261124_150030`](results/20261124_150030/report.md) (current), [`results/20261122_163350`](results/20261122_163350/report.md) and [`results/20261122_140046`](results/20261122_140046/report.md) (before the extraction generalisation) |

---

## Summary

| Area | Metric | Result |
|---|---|---|
| Document processing | documents processed to `ready` | **22 / 22 (100%)** |
| Information extraction (notebook B) | entity-level micro F1 | **0.984** |
| Information extraction (held-out, frozen) | entity-level micro F1 · sample products found | **0.829** · **41 / 57** |
| Query routing | accuracy (31 questions) | **93.5%** |
| SQL generation | execution accuracy, 18 questions × 3 runs | **100%** |
| Consistency | same route / same retrieval / same SQL answer over 3 runs | **100% / 96.8% / 100%** |
| Performance | end-to-end latency mean / p50 / p95 | **4.31 s / 4.09 s / 7.25 s** |
| Cost | per chat question · per processed page | **$0.00082** (7,230 tokens) · **$0.0015** |

---

## Datasets

| Set | Documents | Used for |
|---|---|---|
| Notebook A | 10 PDFs: earnings releases, an investor presentation, an infographic, bank financial statements, credit-card terms (RIPLAY), laptop spec sheets | 31 chat questions: routing, latency, consistency |
| Notebook B | 10 PDFs: a car price list, credit-card terms, laptop spec sheets | Extraction against a full hand-labelled reference (25 products) |
| Tuning | 3 PDFs: a 43-page reseller price list (Cisco), a 21-page MSRP list (Datavideo), a laptop spec sheet. They were the held-out set until their output was inspected to fix the extraction prompt | Extraction against a sampled reference (22 products) |
| **Held-out (frozen)** | 4 public PDFs of kinds absent from the other sets, frozen on 24 Nov 2026 *before* the prompt was changed: a B2B price list with part numbers and USD/CAD prices (Logitech, p. 1–10), a part-number-only price list (Gigamon, p. 1–12), Indonesian monthly business internet plans per region (Biznet), a multi-product projector spec guide without prices (Epson) | Extraction against a reference sampled by a fixed rule (every n-th item; Biznet complete): 57 products. Only aggregate scores are looked at |
| SQL reference | a `features` table built from the notebook B ground truth | 18 NL2SQL questions with hand-written gold SQL |

Documents are in English and Indonesian, 1 to 43 pages, 229 pages in total.

---

## 1. Document processing

Every file is uploaded through the Library service and processed by the real queue worker
(Docling → vision → profile → chunking and embedding → extraction).

| Metric | Result |
|---|---|
| Documents reaching `ready` | 22 / 22 |
| Pages | 229 |
| Processing time | 1,514 s (6.6 s per page) |
| AI cost | $0.341 total |

| File | Set | Pages | Chunks | Seconds | Cost (USD) |
|---|---|---:|---:|---:|---:|
| en_cisco_price_list_reseller.pdf | T | 43 | 325 | 540.4 | 0.1115 |
| en_lenovo_fy2526_q3_presentation.pdf | A | 31 | 71 | 33.5 | 0.0111 |
| en_hp_q4_fy2025_earnings.pdf | A | 21 | 94 | 36.5 | 0.0146 |
| en_datavideo_msrp_2017.pdf | T | 21 | 87 | 86.2 | 0.0204 |
| id_bank_mega_publikasi_des2025.pdf | A | 16 | 202 | 107.7 | 0.0354 |
| en_epson_projector_range_guide_2025.pdf | V | 16 | 168 | 107.7 | 0.0299 |
| en_gigamon_dir_pricelist_2021.pdf | V | 12 | 87 | 94.3 | 0.0263 |
| en_lenovo_t14_gen5_intel.pdf | AB | 11 | 95 | 21.3 | 0.0064 |
| en_lenovo_t14s_2in1_gen1.pdf | T | 11 | 94 | 20.4 | 0.0059 |
| en_lenovo_t14s_gen5.pdf | B | 10 | 87 | 19.4 | 0.0051 |
| en_logitech_b2b_msrp_2024.pdf | V | 10 | 119 | 108.6 | 0.0335 |
| id_biznet_business_pricelist.pdf | V | 6 | 10 | 12.2 | 0.0014 |
| en_hp_probook4_g1i.pdf | AB | 5 | 37 | 32.5 | 0.0045 |
| id_mega_riplay_gold.pdf | AB | 3 | 19 | 18.3 | 0.0038 |
| id_cimb_riplay_mc_gold.pdf | AB | 2 | 15 | 16.3 | 0.0029 |
| id_icbc_creditcard.pdf | AB | 2 | 14 | 12.3 | 0.0028 |
| id_cimb_riplay_mc_platinum.pdf | B | 2 | 14 | 14.2 | 0.0035 |
| id_cimb_riplay_mc_world.pdf | B | 2 | 13 | 22.4 | 0.0037 |
| id_cimb_riplay_octo.pdf | B | 2 | 11 | 21.4 | 0.0035 |
| id_cimb_niaga_publikasi_des2025.pdf | A | 1 | 68 | 163.4 | 0.0122 |
| en_lenovo_q2_fy2526_infographic.pdf | A | 1 | 4 | 12.2 | 0.0013 |
| id_kia_pricelist_jakarta.pdf | B | 1 | 2 | 13.2 | 0.0010 |

Extraction now uses units of at most 1,500 tokens (was 4,000), so dense price lists cost about
twice as much as before (Cisco $0.056 → $0.112, Datavideo $0.012 → $0.020); small documents are
unchanged.

---

## 2. Information extraction

Scored per product (entity level): rows that name the same product are merged, then each field
is compared with the reference. A row names a reference product by its `model_code` when both
have one, otherwise by name tokens. Prices match within ±0.5%. Advantages and disadvantages are
free text and are judged by an LLM. **Core F1** pools brand, product, price and currency only, so
it compares with runs from before the `code` field existed.

### Before and after the extraction generalisation

The first held-out set (now the tuning set) scored 0.806 while notebook B scored 0.976: the
prompt had been shaped by one-product documents. Part numbers were dropped (no field for them)
and accessories with their own price were skipped. The fix: a `model_code` field, product names
built from product line to variant, "every priced or coded item in a price list is a product",
and shorter extraction units.

Baseline = the previous prompt run in [`extraction_lab.py`](extraction_lab.py) on the same
parsed documents; after = this report.

| Set | Core F1, before → after | Products found, before → after | Core precision, before → after |
|---|---|---|---|
| Notebook B | 1.000 → **1.000** | 25/25 → **25/25** | 1.000 → **1.000** |
| Tuning | 0.885 → **0.951** | 18/22 → **20/22** | 0.986 → **1.000** |
| **Held-out (frozen)** | 0.734 → **0.821** | 39/57 → **41/57** | 0.899 → **0.973** |

These are single runs, and extraction varies between runs. On the held-out set a lab run of the
final prompt found 47/57 (core F1 0.856); this full run found 41/57. Most of the variation is in
the Epson guide (9–13 of 14).

### Notebook B (full reference: 25 products)

| Field | Precision | Recall | F1 |
|---|---:|---:|---:|
| brand | 1.000 | 1.000 | **1.000** |
| product | 1.000 | 1.000 | **1.000** |
| price | 1.000 | 1.000 | **1.000** |
| currency | 1.000 | 1.000 | **1.000** |
| advantages | 0.889 | 0.889 | **0.889** |
| **micro** | 0.979 | 0.989 | **0.984** |

All 25 reference products are found, and none of the extracted products is spurious. These
documents have no part numbers. One extracted `disadvantages` value counts as a false positive.

### Tuning set (sampled reference: 22 products)

| Field | Precision | Recall | F1 |
|---|---:|---:|---:|
| brand | 1.000 | 0.909 | **0.952** |
| product | 1.000 | 0.909 | **0.952** |
| code | 1.000 | 0.818 | **0.900** |
| price | 1.000 | 0.905 | **0.950** |
| currency | 1.000 | 0.905 | **0.950** |
| **micro** | 1.000 | 0.897 | **0.946** |

Pages that show a price and have at least one extracted priced row: **98.4%** (was 60% with
the previous prompt and 4,000-token units).

### Held-out, frozen (sampled reference: 57 products)

| Field | Precision | Recall | F1 |
|---|---:|---:|---:|
| brand | 1.000 | 0.719 | **0.837** |
| product | 0.951 | 0.684 | **0.796** |
| code | 1.000 | 0.762 | **0.865** |
| price | 0.938 | 0.698 | **0.800** |
| currency | 1.000 | 0.744 | **0.853** |
| **micro** | 0.978 | 0.719 | **0.829** |

| Document | Rows extracted | Sample products found | Price-page coverage | Misses |
|---|---:|---|---|---|
| en_logitech_b2b_msrp_2024.pdf | 437 | 12/13 | 10/10 | 1 extracted, unidentified |
| en_gigamon_dir_pricelist_2021.pdf | 311 | 14/15 | 12/12 | 1 extracted, unidentified |
| id_biznet_business_pricelist.pdf | 6 | 6/15 | 2/2 | 9 not extracted |
| en_epson_projector_range_guide_2025.pdf | 86 | 9/14 | – | 5 not extracted |

Precision stays high (0.95–1.00); the misses are recall. **Known weak spots:** per-region plan
tables (Biznet: the same plans listed again for other regions are not extracted) and wide
multi-model spec tables (Epson). No rule was added for them: the only evidence comes from the
held-out set, and tuning on it would make it useless. The next step is to add documents of these
kinds to the tuning set and freeze a fresh held-out set.

---

## 3. Query routing (notebook A)

Each question is labelled with the source that answers it: `sql` (prices and calculations over
prices), `vector` (document text), `both`, or `none` (no document needed).

**Accuracy: 29 / 31 (93.5%).**

| Route | Precision | Recall | F1 |
|---|---:|---:|---:|
| sql | 0.875 | 0.875 | 0.875 |
| vector | 0.938 | 1.000 | 0.968 |
| both | 1.000 | 0.750 | 0.857 |
| none | 1.000 | 1.000 | 1.000 |

Confusion matrix (rows = expected, columns = chosen):

| | sql | vector | both | none |
|---|---:|---:|---:|---:|
| **sql** | 7 | 1 | 0 | 0 |
| **vector** | 0 | 15 | 0 | 0 |
| **both** | 1 | 0 | 3 | 0 |
| **none** | 0 | 0 | 0 | 4 |

Misses: `r_sql_t14_price` (expected `sql`, chose `vector`) and `r_both_tb4_cheapest` (expected
`both`, chose `sql`) — the same two as in the previous runs.

---

## 4. SQL generation

Execution accuracy, as in Spider/BIRD. The NL2SQL service generates and runs SQL on the reference
table, and a hand-written gold query runs in the same sandbox. A result is correct when it has
the same rows and every gold answer column appears with the same values (in order, when the
question asks for an order).

| Metric | Result |
|---|---|
| Executable queries | 100% |
| Execution accuracy, first run | 18 / 18 (100%) |
| Execution accuracy, all runs | 54 / 54 (100%) |
| Mean NL2SQL latency | 1.40 s (p95 2.20 s) |

The 18 questions cover minimum and maximum (with ties), averages, counts, threshold and range
filters, sorting, second-cheapest (ranking), spread (max − min), per-brand grouping, NULL
handling and attribute filters. The new `model_code` column does not change any of them.

---

## 5. Performance

Wall-clock time per chat question (router → retrieval → answer), over 93 calls (31 questions ×
3 runs).

| Scope | n | Mean (ms) | p50 (ms) | p95 (ms) |
|---|---:|---:|---:|---:|
| **end-to-end** | 93 | **4,311** | **4,095** | **7,253** |
| route `none` | 12 | 2,589 | 2,608 | 2,998 |
| route `vector` | 48 | 3,752 | 3,435 | 5,287 |
| route `sql` | 24 | 5,274 | 4,934 | 7,913 |
| route `both` | 9 | 7,020 | 6,892 | 8,564 |
| stage: router | 93 | 1,381 | 1,315 | 1,856 |
| stage: SQL | 33 | 2,007 | 1,485 | 4,708 |
| stage: vector search | 60 | 388 | 319 | 641 |
| stage: answer (synthesizer) | 93 | 1,896 | 1,634 | 3,740 |

Average cost per chat question: **7,230 tokens, $0.00082**.

---

## 6. Consistency

Each question is asked 3 times in a new conversation. A question is consistent when every run
gives the same result.

| Check | Questions | Consistent |
|---|---:|---:|
| Same route | 31 | **100%** |
| Same retrieval (SQL status and row count, pages of retrieved chunks) | 31 | **96.8%** (30 / 31) |
| Same SQL answer (reference table) | 18 | **100%** |
| SQL answer correct in every run | 18 | **100%** |

The exact SQL text matches in only 11.1% of the repeats. The queries are worded differently, but
they return the same answer.

---

## How to run

```bash
python eval/run_eval.py --repeats 3            # full run
python eval/run_eval.py --smoke                # 2 documents per notebook, 4 questions per set
python eval/run_eval.py --rescore <RUN>        # rescore an existing run with the current ground truth
python eval/extraction_lab.py                  # extraction only, on cached parses: tuning + notebook B
python eval/extraction_lab.py --sets validation  # the frozen held-out set: aggregate scores only
```

Options: `--no-judge` skips the LLM judge for free-text fields, and `--no-validation` skips the
tuning and held-out sets. Each run writes `report.md` and `report.json` to
`eval/results/<timestamp>/`. The lab parses each document once (cached in `data/eval_lab/`) and
re-runs profile + extraction with the current prompts; `--show` lists misses and other entities
(never for the held-out set), `--max-unit-tokens` tries another extraction unit size.

**Rule for the held-out set:** never inspect its extracted rows while changing prompts. When it
has been used to tune, move it to the tuning set and freeze a new one.
