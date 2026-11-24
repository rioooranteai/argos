# ArgosAI evaluation — 2026-11-24T15:00:36

Repeats per question: 3. Notebook A: 10 sources, notebook B: 10 sources (limit 10).

## Summary

| Area | Metric | Result |
|---|---|---|
| Document processing | documents processed to `ready` | 22/22 (100.0%) |
| Information extraction | field-level micro F1 (macro F1) | 0.984 (0.978) |
| Information extraction | tuning set: micro F1 / products found | 0.946 / 20/22 |
| Information extraction | held-out set: micro F1 / products found | 0.829 / 41/57 |
| Query routing | accuracy, strict / lenient | 93.5% / 93.5% |
| SQL generation | execution accuracy (first run / all runs) | 100.0% / 100.0% |
| Performance | end-to-end latency mean / p50 / p95 | 4311.0 ms / 4094.6 ms / 7252.8 ms |
| Consistency | same route / same retrieval / same SQL answer over 3 runs | 100.0% / 96.8% / 100.0% |

## 1. Document processing

229 pages in 1514.4 s (6.61 s/page), AI cost $0.3407.

| File | Set | Stage | Pages | Chunks | Vision calls | Seconds | Cost (USD) |
|---|---|---|---|---|---|---|---|
| en_hp_probook4_g1i.pdf | AB | ready | 5 | 37 | 1 | 32.5 | 0.0045 |
| en_hp_q4_fy2025_earnings.pdf | A | ready | 21 | 94 | 0 | 36.5 | 0.0146 |
| en_lenovo_fy2526_q3_presentation.pdf | A | ready | 31 | 71 | 18 | 33.5 | 0.0111 |
| en_lenovo_q2_fy2526_infographic.pdf | A | ready | 1 | 4 | 2 | 12.2 | 0.0013 |
| en_lenovo_t14_gen5_intel.pdf | AB | ready | 11 | 95 | 7 | 21.3 | 0.0064 |
| id_bank_mega_publikasi_des2025.pdf | A | ready | 16 | 202 | 0 | 107.7 | 0.0354 |
| id_cimb_niaga_publikasi_des2025.pdf | A | ready | 1 | 68 | 2 | 163.4 | 0.0122 |
| id_cimb_riplay_mc_gold.pdf | AB | ready | 2 | 15 | 1 | 16.3 | 0.0029 |
| id_icbc_creditcard.pdf | AB | ready | 2 | 14 | 0 | 12.3 | 0.0028 |
| id_mega_riplay_gold.pdf | AB | ready | 3 | 19 | 2 | 18.3 | 0.0038 |
| en_lenovo_t14s_gen5.pdf | B | ready | 10 | 87 | 6 | 19.4 | 0.0051 |
| id_cimb_riplay_mc_platinum.pdf | B | ready | 2 | 14 | 2 | 14.2 | 0.0035 |
| id_cimb_riplay_mc_world.pdf | B | ready | 2 | 13 | 1 | 22.4 | 0.0037 |
| id_cimb_riplay_octo.pdf | B | ready | 2 | 11 | 2 | 21.4 | 0.0035 |
| id_kia_pricelist_jakarta.pdf | B | ready | 1 | 2 | 0 | 13.2 | 0.001 |
| en_cisco_price_list_reseller.pdf | T | ready | 43 | 325 | 0 | 540.4 | 0.1115 |
| en_datavideo_msrp_2017.pdf | T | ready | 21 | 87 | 1 | 86.2 | 0.0204 |
| en_lenovo_t14s_2in1_gen1.pdf | T | ready | 11 | 94 | 7 | 20.4 | 0.0059 |
| en_epson_projector_range_guide_2025.pdf | V | ready | 16 | 168 | 0 | 107.7 | 0.0299 |
| en_gigamon_dir_pricelist_2021.pdf | V | ready | 12 | 87 | 0 | 94.3 | 0.0263 |
| en_logitech_b2b_msrp_2024.pdf | V | ready | 10 | 119 | 0 | 108.6 | 0.0335 |
| id_biznet_business_pricelist.pdf | V | ready | 6 | 10 | 2 | 12.2 | 0.0014 |

## 2. Information extraction (notebook B, entity level)

| Field | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| brand | 1.0 | 1.0 | 1.0 | 25 | 0 | 0 |
| product | 1.0 | 1.0 | 1.0 | 25 | 0 | 0 |
| code | – | – | – | 0 | 0 | 0 |
| price | 1.0 | 1.0 | 1.0 | 18 | 0 | 0 |
| currency | 1.0 | 1.0 | 1.0 | 18 | 0 | 0 |
| advantages | 0.889 | 0.889 | 0.889 | 8 | 1 | 1 |
| disadvantages | 0.0 | – | – | 0 | 1 | 0 |
| **micro** | 0.979 | 0.989 | **0.984** | 94 | 2 | 1 |

| Document | Rows extracted | Products found | Spurious entities |
|---|---|---|---|
| id_kia_pricelist_jakarta.pdf | 15 | 15/15 | – |
| id_cimb_riplay_mc_gold.pdf | 3 | 1/1 | – |
| id_cimb_riplay_mc_platinum.pdf | 2 | 1/1 | – |
| id_cimb_riplay_mc_world.pdf | 4 | 1/1 | – |
| id_cimb_riplay_octo.pdf | 3 | 1/1 | – |
| id_mega_riplay_gold.pdf | 6 | 1/1 | – |
| id_icbc_creditcard.pdf | 8 | 2/2 | – |
| en_lenovo_t14_gen5_intel.pdf | 8 | 1/1 | – |
| en_lenovo_t14s_gen5.pdf | 6 | 1/1 | – |
| en_hp_probook4_g1i.pdf | 7 | 1/1 | – |

### Tuning set (eval/tuning-files, inspected while tuning; sample reference)

Sample products found: 20/22. Pages showing prices with an extracted priced row: 98.4%. Invented prices (documents without prices): 0.

| Field | Precision* | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| brand | 1.0 | 0.909 | 0.952 | 20 | 0 | 2 |
| product | 1.0 | 0.909 | 0.952 | 20 | 0 | 2 |
| code | 1.0 | 0.818 | 0.9 | 9 | 0 | 2 |
| price | 1.0 | 0.905 | 0.95 | 19 | 0 | 2 |
| currency | 1.0 | 0.905 | 0.95 | 19 | 0 | 2 |
| advantages | – | – | – | 0 | 0 | 0 |
| disadvantages | – | – | – | 0 | 0 | 0 |
| **micro** | 1.0 | 0.897 | **0.946** | 87 | 0 | 10 |

*On a sample reference, precision counts only the sampled products' fields.

| Document | Rows | Sample found | Price-page coverage | Misses | Other entities |
|---|---|---|---|---|---|
| en_lenovo_t14s_2in1_gen1.pdf | 7 | 1/1 | – | – | – |
| en_datavideo_msrp_2017.pdf | 265 | 10/11 | 19/20 | extracted, unidentified (same price): 1 | KMU-100, GoKITS GO-2CAM, GO-3CAM, GO-1KMU, GO-2KMU, GO-650R, GO-650SR, GO-REPLAY, EPB-1100 Educator's Production Bundle, EPB-2100 Educator's Production Bundle, TG-100, BC-50 … |
| en_cisco_price_list_reseller.pdf | 1954 | 9/10 | 43/43 | extracted, unidentified (same price): 1 | 350 Series PC Card Adapter w/128-bit WEP 40 Pack, 350 Series PCI Adapter w/128-bit WEP 10 Pack, 350 Series PCI Adapter w/RP-TNC,Dipole Antenna,128-bit WEP, 350 Series PC Card w/Dual MMCX Connectors and 128-bit WEP, 350 Series PC Card w/Dual MMCX and 128-bit WEP 40 Pack, 350 Series Workgroup Bridge w/Captured Antenna / 128-bit WEP, 350 Series Workgroup Bridge w/Dual RP-TNC and 128-bit WEP, 350 Series 11Mbps, DSSS Bridge w/128-bit WEP, 350 Series 11Mbps, DSSS Bridge w/128-bit WEP, 350 Series 11Mbps, DSSS Bridge w/128-bit WEP, 350 Series Site Survey Kit, 350 Series Site Survey Kit … |

### Held-out validation (eval/validation-files, frozen; sample reference except Biznet)

Sample products found: 41/57. Pages showing prices with an extracted priced row: 100.0%. Invented prices (documents without prices): 0.

| Field | Precision* | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| brand | 1.0 | 0.719 | 0.837 | 41 | 0 | 16 |
| product | 0.951 | 0.684 | 0.796 | 39 | 2 | 18 |
| code | 1.0 | 0.762 | 0.865 | 32 | 0 | 10 |
| price | 0.938 | 0.698 | 0.8 | 30 | 2 | 13 |
| currency | 1.0 | 0.744 | 0.853 | 32 | 0 | 11 |
| advantages | – | – | – | 0 | 0 | 0 |
| disadvantages | – | – | – | 0 | 0 | 0 |
| **micro** | 0.978 | 0.719 | **0.829** | 174 | 4 | 68 |

*On a sample reference, precision counts only the sampled products' fields.

| Document | Rows | Sample found | Price-page coverage | Misses |
|---|---|---|---|---|
| en_logitech_b2b_msrp_2024.pdf | 437 | 12/13 | 10/10 | extracted, unidentified (same price): 1 |
| en_gigamon_dir_pricelist_2021.pdf | 311 | 14/15 | 12/12 | extracted, unidentified (same price): 1 |
| id_biznet_business_pricelist.pdf | 6 | 6/15 | 2/2 | not extracted: 9 |
| en_epson_projector_range_guide_2025.pdf | 86 | 9/14 | – | not extracted: 5 |

## 3. Query routing (notebook A)

| Route | Precision | Recall | F1 |
|---|---|---|---|
| sql | 0.875 | 0.875 | 0.875 |
| vector | 0.938 | 1.0 | 0.968 |
| both | 1.0 | 0.75 | 0.857 |
| none | 1.0 | 1.0 | 1.0 |

Confusion (rows = expected, columns = chosen):

| | sql | vector | both | none |
|---|---|---|---|---|
| sql | 7 | 1 | 0 | 0 |
| vector | 0 | 15 | 0 | 0 |
| both | 1 | 0 | 3 | 0 |
| none | 0 | 0 | 0 | 4 |

Misses:

- `r_sql_t14_price`: expected sql, got vector
- `r_both_tb4_cheapest`: expected both, got sql

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
| end-to-end | 93 | 4311.0 | 4094.6 | 7252.8 | 9058.2 |
| route sql | 24 | 5273.6 | 4933.8 | 7912.6 | 8427.7 |
| route vector | 48 | 3752.2 | 3435.2 | 5286.8 | 6156.6 |
| route both | 9 | 7020.3 | 6892.2 | 8563.8 | 9058.2 |
| route none | 12 | 2589.3 | 2608.3 | 2997.8 | 2999.0 |
| stage router | 93 | 1381.0 | 1315.0 | 1856.2 | 2470 |
| stage sql | 33 | 2007.1 | 1485.0 | 4708.2 | 5961 |
| stage synthesizer | 93 | 1896.2 | 1634.0 | 3739.8 | 4493 |
| stage vector | 60 | 387.5 | 319.0 | 641.2 | 2174 |
| NL2SQL (reference table) | 54 | 1402.4 | 1310.0 | 2199.4 | 2891.7 |

Average per question: 7230 tokens, $0.00082.

## 6. Consistency

Chat (notebook A, 31 questions × 3): same route 100.0%, same retrieval 96.8%, both 96.8%.
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
  the logo only) accepts an empty brand.
