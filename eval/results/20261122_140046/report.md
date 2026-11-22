# ArgosAI evaluation — 2026-11-22T14:00:54

Repeats per question: 3. Notebook A: 10 sources, notebook B: 10 sources (limit 10).

## Summary

| Area | Metric | Result |
|---|---|---|
| Document processing | documents processed to `ready` | 18/18 (100.0%) |
| Information extraction | field-level micro F1 (macro F1) | 0.985 (1.0) |
| Query routing | accuracy, strict / lenient | 93.5% / 93.5% |
| SQL generation | execution accuracy (first run / all runs) | 100.0% / 100.0% |
| Performance | end-to-end latency mean / p50 / p95 | 4207.5 ms / 3902.9 ms / 6864.4 ms |
| Consistency | same route / same retrieval / same SQL answer over 3 runs | 100.0% / 77.4% / 100.0% |

## 1. Document processing

185 pages in 1128.4 s (6.1 s/page), AI cost $0.1525.

| File | Set | Stage | Pages | Chunks | Vision calls | Seconds | Cost (USD) |
|---|---|---|---|---|---|---|---|
| en_hp_probook4_g1i.pdf | AB | ready | 5 | 37 | 1 | 36.3 | 0.0033 |
| en_hp_q4_fy2025_earnings.pdf | A | ready | 21 | 94 | 0 | 43.1 | 0.01 |
| en_lenovo_fy2526_q3_presentation.pdf | A | ready | 31 | 71 | 18 | 39.3 | 0.0093 |
| en_lenovo_q2_fy2526_infographic.pdf | A | ready | 1 | 4 | 2 | 15.0 | 0.0012 |
| en_lenovo_t14_gen5_intel.pdf | AB | ready | 11 | 95 | 7 | 17.3 | 0.0042 |
| id_bank_mega_publikasi_des2025.pdf | A | ready | 16 | 202 | 0 | 75.3 | 0.0156 |
| id_cimb_niaga_publikasi_des2025.pdf | A | ready | 1 | 68 | 2 | 104.1 | 0.009 |
| id_cimb_riplay_mc_gold.pdf | AB | ready | 2 | 15 | 1 | 22.4 | 0.0027 |
| id_icbc_creditcard.pdf | AB | ready | 2 | 14 | 0 | 13.3 | 0.0024 |
| id_mega_riplay_gold.pdf | AB | ready | 3 | 19 | 2 | 19.3 | 0.0034 |
| en_lenovo_t14s_gen5.pdf | B | ready | 10 | 87 | 6 | 18.3 | 0.004 |
| id_cimb_riplay_mc_platinum.pdf | B | ready | 2 | 14 | 2 | 18.2 | 0.0033 |
| id_cimb_riplay_mc_world.pdf | B | ready | 2 | 13 | 1 | 21.3 | 0.0031 |
| id_cimb_riplay_octo.pdf | B | ready | 2 | 11 | 2 | 21.3 | 0.0033 |
| id_kia_pricelist_jakarta.pdf | B | ready | 1 | 2 | 0 | 14.3 | 0.0009 |
| en_cisco_price_list_reseller.pdf | V | ready | 43 | 325 | 0 | 553.0 | 0.0614 |
| en_datavideo_msrp_2017.pdf | V | ready | 21 | 87 | 1 | 76.1 | 0.0111 |
| en_lenovo_t14s_2in1_gen1.pdf | V | ready | 11 | 94 | 7 | 20.5 | 0.0043 |

## 2. Information extraction (notebook B, entity level)

| Field | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| brand | 1.0 | 1.0 | 1.0 | 25 | 0 | 0 |
| product | 1.0 | 1.0 | 1.0 | 25 | 0 | 0 |
| price | 1.0 | 1.0 | 1.0 | 20 | 0 | 0 |
| currency | 1.0 | 1.0 | 1.0 | 20 | 0 | 0 |
| advantages | 1.0 | 1.0 | 1.0 | 10 | 0 | 0 |
| disadvantages | 0.0 | – | – | 0 | 3 | 0 |
| **micro** | 0.971 | 1.0 | **0.985** | 100 | 3 | 0 |

| Document | Rows extracted | Products found | Spurious entities |
|---|---|---|---|
| id_kia_pricelist_jakarta.pdf | 15 | 15/15 | – |
| id_cimb_riplay_mc_gold.pdf | 2 | 1/1 | – |
| id_cimb_riplay_mc_platinum.pdf | 2 | 1/1 | – |
| id_cimb_riplay_mc_world.pdf | 3 | 1/1 | – |
| id_cimb_riplay_octo.pdf | 4 | 1/1 | – |
| id_mega_riplay_gold.pdf | 4 | 1/1 | – |
| id_icbc_creditcard.pdf | 4 | 2/2 | – |
| en_lenovo_t14_gen5_intel.pdf | 4 | 1/1 | – |
| en_lenovo_t14s_gen5.pdf | 4 | 1/1 | – |
| en_hp_probook4_g1i.pdf | 5 | 1/1 | – |

### Held-out validation (eval/validation-files, sample reference: recall and field accuracy)

| Field | Precision* | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| brand | 1.0 | 0.818 | 0.9 | 18 | 0 | 4 |
| product | 1.0 | 0.818 | 0.9 | 18 | 0 | 4 |
| price | 0.941 | 0.762 | 0.842 | 16 | 1 | 5 |
| currency | 1.0 | 0.81 | 0.895 | 17 | 0 | 4 |
| advantages | – | – | – | 0 | 0 | 0 |
| disadvantages | – | – | – | 0 | 0 | 0 |
| **micro** | 0.986 | 0.802 | **0.885** | 69 | 1 | 17 |

*Precision counts only the sampled products' fields; other extracted products are listed below.

| Document | Rows extracted | Sample products found | Other entities |
|---|---|---|---|
| en_lenovo_t14s_2in1_gen1.pdf | 4 | 1/1 | – |
| en_datavideo_msrp_2017.pdf | 159 | 11/11 | GO-2CAM, GO-3CAM, GO-1KMU, GO-2KMU, GO-650R, GO-650SR, GO-REPLAY, EPB-1100 Educator's Production Bundle, EPB-2100 Educator's Production Bundle, TG-100, BC-50, PTC-150T … |
| en_cisco_price_list_reseller.pdf | 1685 | 6/10 | 350 Series PC Card, 350 Series PC Card Adapter 40 Pack, 350 Series PCI Adapter 10 Pack, 350 Series PCI Adapter, 350 Series PC Card 40 Pack, 350 Series Workgroup Bridge, 350 Series Bridge, 350 Series Site Survey Kit, 350 Series Access Point - A, 350 Series Access Point - J, 350 Series Access Point - E, 350 Series AP … |

## 3. Query routing (notebook A)

| Route | Precision | Recall | F1 |
|---|---|---|---|
| sql | 1.0 | 0.875 | 0.933 |
| vector | 0.882 | 1.0 | 0.938 |
| both | 1.0 | 0.75 | 0.857 |
| none | 1.0 | 1.0 | 1.0 |

Confusion (rows = expected, columns = chosen):

| | sql | vector | both | none |
|---|---|---|---|---|
| sql | 7 | 1 | 0 | 0 |
| vector | 0 | 15 | 0 | 0 |
| both | 0 | 1 | 3 | 0 |
| none | 0 | 0 | 0 | 4 |

Misses:

- `r_sql_t14_price`: expected sql, got vector
- `r_both_tb4_cheapest`: expected both, got vector

## 4. SQL generation (reference table)

Executable: 100.0%. Execution accuracy: 100.0%.

| Question | Correct | Detail |
|---|---|---|
| `s_cheapest` | ✅ | match |
| `s_most_expensive` | ✅ | match |
| `s_avg_sonet` | ✅ | match |
| `s_count_seltos` | ✅ | match |
| `s_sonet_under_300` | ✅ | match |
| `s_seltos_desc` | ✅ | match |
| `s_between` | ✅ | match |
| `s_sonet_spread` | ✅ | match |
| `s_second_cheapest_car` | ✅ | match |
| `s_highest_fee_card` | ✅ | match |
| `s_free_cards` | ✅ | match |
| `s_no_price` | ✅ | match |
| `s_count_priced` | ✅ | match |
| `s_avg_icbc` | ✅ | match |
| `s_count_above_400` | ✅ | match |
| `s_per_brand_count` | ✅ | match |
| `s_lenovo_products` | ✅ | match |
| `s_carens_7_seats` | ✅ | match |

## 5. Performance

| Scope | n | Mean | p50 | p95 | Max |
|---|---|---|---|---|---|
| end-to-end | 93 | 4207.5 | 3902.9 | 6864.4 | 8121.4 |
| route sql | 21 | 5145.5 | 4881.5 | 6978.0 | 7579.6 |
| route vector | 51 | 3784.0 | 3445.6 | 5215.1 | 5623.9 |
| route both | 9 | 6303.8 | 6622.7 | 7648.9 | 8121.4 |
| route none | 12 | 2794.2 | 2636.4 | 3594.0 | 3782.2 |
| stage router | 93 | 1383.5 | 1364.0 | 1849.0 | 2127 |
| stage sql | 30 | 1908.5 | 1683.5 | 3533.4 | 3631 |
| stage synthesizer | 93 | 1886.6 | 1559.0 | 3468.8 | 3971 |
| stage vector | 67 | 413.0 | 368.0 | 568.1 | 759 |
| NL2SQL (reference table) | 54 | 1580.7 | 1446.0 | 2498.6 | 4367.0 |

Average per question: 6776 tokens, $0.00077.

## 6. Consistency

Chat (notebook A, 31 questions × 3): same route 100.0%, same retrieval 77.4%, both 77.4%.
SQL (reference table, 18 questions × 3): same answer 100.0% (correct in every run: 100.0%); same SQL text 11.1% — the wording of the SQL may vary while the answer stays the same.

## Method

- **Document processing** — every file is uploaded through the Library service and processed by the
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
  the per-field F1.
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
  the logo only) accepts an empty brand.
