# CIO Wave 2 living scoreboard

GitHub is source of truth. Drive mirror: folder **TradeAI CIO Ops** `1rRSmvAeO37z2PyyrIYtd2C5ngwHsAIqH`. File upsert: **gog --replace** on blob IDs (MCP cannot write). Native Doc/Sheet IDs stay put.

> **Blob id correction (2026-08-29):** the md blob is `1kNRoyK_Tq8FNUMxrwjNDRB2AZCqnxjOP` — capital **O**. The overnight prompt wrote a zero, which 404s. `1W04_1pATgfewyf8gp-WVIo8cqc26c4WQ` holds `CIO_WAVE2_SCOREBOARD.json`, not the census; the census has no blob yet.

Authority: **READ_ONLY_ADVISORY**. MBI: **0**. INTERDICT: **0** (left as found).

Resume cursor: first slice with status != DONE.

---

## NOW

Updated by slice 12. Pin advanced 9f13273b (#619) → **d53fde4c (#620)** since the
last NOW block; slices 08–11 sha/PR filled in below. Live drift recorded, not
smoothed: `watch_block` 21 → 26 and `reentry_near` 4 → 25 are the #620 Surface A
overlay landing, and `with_case_summary` 323 → 10 is the product cap-10 view (the
CASE_SUMMARY store is still 323 — item 87 will label this on the card).

| Field | Value |
|-------|--------|
| CURRENT pin | `53794d82` (**#623 slices 32–41**, promoted 2026-08-29T03:06:57Z) |
| origin/main | `53794d82` |
| `/api/v2/health` | 200 |
| `/v3/cio` | 200 |
| `/api/v3/cio/home` | 200 · earnings 10 · NEW_POSITION_IF 5 · telegram_sent false · **coverage** Class D |
| plans | open 575 · draft 350 · proposed 224 · accepted 1 · cancelled 269 (hygiene 267) · with_hermes 323 |
| plans by situation | S3 314 · S1 149 · S6 59 · S5 35 · S7 11 · S0 7 |
| CASE_SUMMARY ACTIVE | 323 (store) · 10 (product cap) |
| RESEARCH_REFERENCE | 443 (CANDIDATE) |
| earnings | 10 · commentary UNAVAILABLE |
| NEW_POSITION_IF | NKE/PFSI/PRIM/SH/XLU **CURRENT** |
| cash | PRESENT $630,784.82 |
| watch_block | 26 · ready 0 named · fires_s7=false |
| checkpoints | 152 (Wave 1 slice 8) |
| **holdings_thesis_coverage** | **held_n=15** current=15 unavail=0 · held_n_including_dust=19 · dust_n=4 · instrument_id_n=3 |
| **dust (12a)** | `dust_residual@v1` · market_value < **$50**/ticker aggregated across accounts · JEPI 22.66 · LDOS 31.16 · SCHG 8.09 · SRNE 0.90 · **no lot deleted** |
| **instrument_id (12)** | 12507E201 · 543354104 · 628518102 — CUSIP, `is_ticker=false`, never a ticker field |
| **coverage (home)** | held=15 thesis_count=15 **with_plan=11** (was 1) with_research · watch_block=26 watch_ready=0 reentry_near=25 with_case_summary=10 |
| **with_plan definition** | distinct **non-dust held** tickers with ≥1 **open S1/S3/S5/S6** plan, counted over the **whole 575-plan open store** — not the 12-row CIO NOW window |
| **identity (13)** | 111 rows · resolvable **100%** · stamped **4.5%** · registry 10,279 entities / 5,277 symbols · **minted 0** |
| **identity register (14)** | would_register_n **0** · `--apply` not run · cap 30 |
| **dry harness** | `TRADEAI_ROOT=CURRENT` is required — without it root-less collectors report reentry 43 / watch 0 instead of 70 / 26 |
| **graph_impact (15/16)** | S6 only · 8 S6 symbols · 5 attached · SCHD 5/13 · AMANX 5/13 · DIV 5/11 · SPCX 5/8 · **BND 0/0** · skipped CASH/QCOM (not held) + SRNE (dust) |
| **identity lookup (17)** | RESOLVED / UNRESOLVED / **LOOKUP_FAILED** / NOT_APPLICABLE — a registry read failure no longer reads as a clean negative |
| **research fails 7d (19)** | 228 · cost_cap **130** · execution_language 93 · truncated 3 · timeout 1 · provider_error 1 · retryable **5** · **worker_bug 0** |
| **cost_cap two shapes** | HTTP 429 `COST_CAP_EXCEEDED` 82 + HTTP 500 `RESERVATION_FAILED` 114 — same daily cap; classifying on the code would file 114 as provider errors |
| **research quality (25)** | 468 completed · VALID 392 · PARTIAL 74 · INSUFFICIENT 2 · **attachable 466** · rule `VALID\|PARTIAL` |
| **attach backfill (24)** | **would_attach 2, not 0** — plan_5463afc7bc04 · plan_9f4df5b991f3. Dry only, not applied. |
| **checkpoints (27)** | due **0** · would_bind 152 → **106** after dust filter · nothing written |
| **lessons (28/29)** | 328 PROVISIONAL / REVIEW_READY · **policy 0** · cannot_become_policy true |
| **memory (30/31)** | CASE_SUMMARY 328 ACTIVE · RESEARCH_REFERENCE 448 CANDIDATE / **0 ACTIVE** · receipts 338/757 carry memory_type+promotable (chronological split) |
| **12a activation fix** | live served `held_n=19` after promote — operator product was serving a pre-12a persisted brief; freshness check now detects the older schema |
| **authorized apply: attach** | 2 of 2 (`plan_5463afc7bc04`, `plan_9f4df5b991f3`) · would_attach now **0** · CASE_SUMMARY stayed **328** (no double-mint) · the 474 untouched |
| **authorized apply: orphan S6** | **20 cancelled** — CASH 1 · QCOM 1 · **SRNE 18** (dust) · notify false · append-only 4,958 → 4,998 lines · nothing deleted |
| **live after applies** | `held_n` **15** · `with_plan` **11** · `graph_impact` 5 S6, **0 skipped** · telegram_sent false |
| **cash two writers (40)** | position rows **$630,784.82** vs portfolio_totals **$578,107.50** · Δ **$52,677.32** · both printed, never merged |
| **holdings freshness (39)** | as_of 2026-08-26 · reprice 08-28 16:45 · **3 days old** · `DATA_STALE` + `REPRICE_AHEAD_OF_POSITIONS` |
| **checkpoints (32)** | 523 · 0 carry plan_id · rate **UNCOMPUTABLE** (not 0%) · **148 on CASH**, 50 on dust |
| **C2 (41)** | dust TRIM **was admitted**; now blocked. AVOID on unheld still admissible. |
| **watch in briefs** | 26 BLOCK **named** (FTH, SWBI, DXCM, ANET, V, SPCX, ABUS, PFLT +18) · READY **0**, never promoted |
| **S6 dust rule** | **SHIPPED.** Root cause was the *disposition* branch, not concentration: a $0.90 residual reads as a 100% loss held 36m, clearing 20% / 6m on every pass — which is why cancelling could not fix it. Dust · CUSIP · empty subjects now skipped; SCHD still fires `weight_28.4pct`; thresholds untouched. |
| **S1 dust rule (Wave 2C)** | S1 had the same disease as S6 via `deep_drawdown_from_basis` — **35 open plans** on JEPI 20 / SRNE 14 / LDOS 1. One shared gate now serves both. |
| **Wave 2C 101–130** | 28 DONE · 2 FIXED (116, 117) · 1 OPEN (118 cost-basis as_of). 35 dust S1 cancelled, slice-12c cap-5 applied → **full held coverage** |
| **held without open S1** | **NONE** — every non-dust held name now carries one |
| **not cancelled** | 19 `DIVI` S1 flagged `not_held` — different reason, no authorisation, surfaced for the operator |
| **Wave 2C 131–160** | 27 DONE · 3 FIXED (131, 132, 160) · 0 open. Both books now name themselves on `/home` and in the CC; `merged: false` |
| **Wave 2C 161–190** | 30 DONE · 0 open. `hermes_result_id` **328 total** = 282 open + 46 cancelled by dust hygiene (reconciles exactly). |
| **$0.001 model receipts** | 46 historical, last `13:46:33Z`; fix `ff09c255` at `13:49:23Z` — **3 min later**. 47 runs since with none. |
| **Wave 2C 191–220** | 30 DONE · 0 open · **no code changed**. Plans: 533 open (S3 320 · S1 120 · S6 40 · S5 35 · S7 11 · S0 7); warehouse 860 total. |
| **item 198 near-miss** | 109 historical duplicate S1 looked like a live guard failure; against the correct #609 boundary (17:09Z) only **9 created since, 0 duplicate symbols**. Guard holds. |
| **Wave 2C 221–250** | 29 DONE · **1 FIXED (236)** · 0 open. Jailbreak scan missed 4 canonical phrasings — fixed in #631. Checkpoints 527, all trading:false / MBI 0. |
| **Wave 2C 251–320** | 68 DONE · **2 FIXED (186/302)** · 0 open. EXEC_LINT adjacency gap — `execute the buy` passed **both** execution-language gates. |
| **Wave 2C COMPLETE** | 101–320: **184 DONE · 9 FIXED · 1 open (118)** across 6 batches |
| **operator judgments 2026-08-29** | one shared grammatical matcher (not word bans); **466 intact**; cash `UNRECONCILED` with S5 refusing a number; open S1 **120 → 16**, 0 duplicates, DIV untouched |
| **cash law** | rows 630,784.82 · totals 578,107.50 · gap **52,677.32 UNRECONCILED** · `cash_for_S5 DATA_UNAVAILABLE_UNTIL_RECONCILED` |
| **item 118** | basis **08-14** · positions **08-26** · priced **08-28** — two weeks apart |
| **cash writer FIXED** | `portfolio_loader` now writes `total_cash` from the is_cash row sum, with `total_cash_source` + `total_cash_written_at`. Field kept, no read-site recompute added, `api_v2:2593` untouched. UNRECONCILED holds until the next reprice, then flips on its own. |
| exec voice | `[T]` / `[D] Nothing requires action today.` |
| reentry | Surface A · 70 names · reentry_total 25 NEAR overlaid · queue 43 · **dual pipes NOT merged** |
| slice 12c would | BAH · CSWC · V · XAR · AMANX (cap 5, notify false) — apply is a separate dry-first step |
| DRIVE | pending this bundle |
| rails | MBI=0 · INTERDICT=0 · notify not enabled · no broker write · no ROTATE · no lot delete |
| slice 02 would/applied | would_mint CURRENT · applied 1 `symbol_prim@v1` · PRIM CURRENT · telegram_sent false |
| slice 03 would/applied | would 5 · applied 5 · SCHG S1 later cancelled (former, not held) |
| surface_a_status | SCHG/AXTI/FATN EXITED · FANG UNAVAILABLE · no invented prices |
| watch_ready_named | ready=[] near=[] · ready_count=0 · fires_s7=false (honest) |


---

## Wave 1 (closed — copied from closeout)

| Slice | PR | What shipped | Wave 2 status |
|------|-----|----------------|---------------|
| 1 attach | #592 | hermes_result_id + deterministic synth | CLOSED |
| 2A | CASE_SUMMARY | ~323 ACTIVE | CLOSED |
| 2B+2C | #594 | earnings, NEW_POSITION_IF, cash, case_summaries | CLOSED |
| 4b | #595 | prod_ product_id | CLOSED |
| 3 | #596 | two reentry books labeled not merged | CLOSED |
| 4 | #597 | persist operator product | CLOSED |
| 5 | #598 | expire stale empty drafts; --apply 267 | CLOSED |
| 6 | #599 | watch_block_summary; fires_s7=false | CLOSED |
| 7 | #600 | NEW_POSITION_IF thesis CURRENT vs UNAVAILABLE | CLOSED |
| 8 | #601 | OutcomeCheckpoint held researched | CLOSED |
| 9 | #602 | CASE_SUMMARY support lessons | CLOSED |
| 10 | #603 | P9.0 voice T/D | CLOSED |
| 11 | #604 | TRIM of non-held blocked | CLOSED |
| 12 | #605 | price outlier quarantine | CLOSED |
| 13 | #606 | QA critical ops alert 24h dedupe | CLOSED |
| 14 | #607 | rebalancer flags AVOID | CLOSED |
| 15 | #608 | subject_guid lookup | CLOSED |
| 16 | #609 | persist ≥1 S3; skip dup open S1 | CLOSED |
| 17 | #610 | home 2B+2C; no Telegram-sent on dashboard | CLOSED |
| 18 | #611 | closeout scoreboard | CLOSED |

Leftovers still forbidden unless a Wave 2 slice explicitly allows a read-only stub: ROTATE-as-action, notify-on, gate loosen, AGENT_COMMITMENT as policy, book merge, cio_run LLM, stop-management files, historical ticker_prices DELETE.

---

## Wave 2 slices

| NN | Title | Status | PR | sha | Rails | Proof |
|----|-------|--------|----|-----|-------|-------|
| 00 | bootstrap scoreboard + Drive | DONE | #612 | `26e61633` | MBI=0 INTERDICT=0 | scoreboard on CURRENT; Drive folder yes |
| 01 | held-universe thesis card | DONE | #613 | `6616d618` | MBI=0 | held_n=19 current=19 unavail=0; no fake thesis |
| 02 | PRIM thesis hole | DONE | #614 | `a8434346` | MBI=0 notify off | sandbox→CIO; PRIM CURRENT; applied 1 |
| 03 | observational S1 held-without-plan | DONE | #615 | `5e48f2b1` | MBI=0 notify off | cap 5; SCHG S1 cancelled (former) |
| 04 | Surface A former-sold status | DONE | #616 | `bb489827` | MBI=0 | SCHG/AXTI/FATN EXITED; FANG UNAVAILABLE |
| 05 | Watch READY/NEAR named; fires_s7=false | DONE | #617 | `6a796e1a` | MBI=0 | ready_symbols named; live 0 READY/NEAR; fires_s7=false |
| 06 | earnings days_to_event + as_of | DONE | #618 | `6bbec1a1` | MBI=0 | days_to_event + as_of |
| 07 | earnings commentary stub | DONE | #619 | `9f13273b` | MBI=0 | commentary UNAVAILABLE |
| 08 | coverage API GET | DONE | #620 | `d53fde4c` | MBI=0 | home.coverage Class D; fail-soft zeros |
| 09 | CC coverage card | DONE | #620 | `d53fde4c` | MBI=0 | cio-coverage-card after TrustStrip |
| 10 | reentry keys not 0 when Surface A has names | DONE | #620 | `d53fde4c` | MBI=0 | dual pipes; reentry_total overlaid from Surface A |
| 11 | thesis count vs held on home | DONE | #620 | `d53fde4c` | MBI=0 | thesis_count/held_n 19/19; superseded by 12a (dust out → 15/15) |
| 12 | holdings truth: instrument_id · DUST_RESIDUAL · with_plan counter · S1 leftovers | DONE | #621 | `5f215504` | MBI=0 INTERDICT=0 no lot delete | held_n 19→15 · dust JEPI/LDOS/SCHG/SRNE · instrument_id 3 · with_plan 1→11 · would_s1 BAH CSWC V XAR AMANX |
| 13 | % subject_guid measured on NEW_POSITION_IF / reentry / watch | DONE | #621 | `5f215504` | no mint · MBI=0 | 111 rows · **resolvable 100%** · **stamped 4.5%** (only NEW_POSITION_IF stamps) · minted 0 |
| 14 | register HELD(non-dust)+ACTIVE watch missing | DONE | #621 | `5f215504` | dry only · **--apply NOT run** | **would_register_n=0** — all 47 considered already registered; cap 30 unused |
| 15 | 1-hop graph_impact same-sector held neighbours | DONE | #621 | `5f215504` | class D · no new store | cap 5 · deterministic · dust excluded both sides · missing map → DATA_UNAVAILABLE |
| 16 | graph_impact on S6 names only | DONE | #621 | `5f215504` | S6 scope only | 8 S6 symbols · 5 attached · SCHD 5/13 · **BND 0/0 honest** · CASH/QCOM/SRNE skipped with reason |
| 17 | identity_lookup_failed ≠ UNRESOLVED | DONE | #621 | `5f215504` | UNRESOLVED still UNRESOLVED · no mint | RESOLVED / UNRESOLVED / LOOKUP_FAILED / NOT_APPLICABLE; failure outranks clean negative |
| 18 | never ticker as security GUID | DONE | #621 | `5f215504` | regression only | ticker_alias_guid UUIDv5 · symbol → aliases · by_symbol[SYM] ≠ SYM (SCHD/CUSIP/V) |
| 19 | Hermes fail histogram last 7d | DONE | #622 | `c3c7b966` | read-only · no requeue · no cap raised | 228 in 7d · **cost_cap 130** · execution_language 93 · truncated 3 · **worker_bug 0** |
| 20 | skip enqueue of non-retryable execution-language | DONE | #622 | `c3c7b966` | opt-in gate · fails soft | never requeued; blocks even beside a retryable truncation; nothing written on block |
| 21 | truncated replay ≤1/plan/day | DONE | #622 | `c3c7b966` | eligibility only · **no cap raised** | MAX_REPLAYS_PER_PLAN_PER_DAY=1 · cost_cap-only history waits for the window |
| 22 | hermes_result_id on new attachable complete | DONE | #622 | `c3c7b966` | unit · no live spend | attachable only on VALID\|PARTIAL + non-failed status; truncated/cost_cap flags refuse |
| 23 | CASE_SUMMARY mints on VALID complete | DONE | #622 | `c3c7b966` | unit · no admit | source_kind `HERMES_VALID_COMPLETE`; dedup on (symbol, plan_id, result_id) |
| 24 | attach backfill dry would_attach | DONE | #622 | `c3c7b966` | dry first · **operator-authorized apply of 2 only** | would_attach was **2, not 0**; both VALID → applied. Now **0**; missing_result_id 254→252; the 474 untouched; CASE_SUMMARY stayed 328 (no double-mint). |
| 25 | VALID/PARTIAL/FAIL counts on product | DONE | #622 | `c3c7b966` | read-only | 468 completed · VALID 392 · PARTIAL 74 · INSUFFICIENT 2 · **attachable 466** |
| 26 | attach rule VALID\|PARTIAL documented | DONE | #622 | `c3c7b966` | **no silent tighten** | on the payload; VALID-only would drop 74 of 466 |
| 27 | due checkpoints observe | DONE | #622 | `c3c7b966` | dry · **due=0** · no apply · no invented PnL | would_bind 152 → **106** after dust filter; JEPI/LDOS/SCHG/SRNE excluded |
| 28 | top 8 PROVISIONAL lessons on product | DONE | #622 | `c3c7b966` | cannot_become_policy true | 328 candidates, all PROVISIONAL/REVIEW_READY, policy_effect false, cap 8 |
| 29 | REVIEW_READY count | DONE | #622 | `c3c7b966` | ceiling REVIEW_READY | REVIEW_READY **328** · **policy 0** · 12 RATIFIED_CONTEXT not_production_policy |
| 30 | memory receipts memory_type+promotable | DONE | #622 | `c3c7b966` | regression | 338/757 carry both — split is chronological, all receipts since 2026-08-28T13:34 have them |
| 31 | no RESEARCH_REFERENCE ACTIVE | DONE | #622 | `c3c7b966` | regression | 448 CANDIDATE · **0 ACTIVE** · CASE_SUMMARY 328 ACTIVE |
| 32 | complete→checkpoint rate exposed | DONE | #623 | `53794d82` | reported, nothing rewritten | 523 checkpoints · **0 with plan_id** · rate **UNCOMPUTABLE** not 0% · 148 on CASH · 50 on dust |
| 33 | remaining P9.0 voice labels | DONE | #623 | `53794d82` | additive · no sentence reworded | temperament.narrative **T** · next_reviews **T** · closest-reentries **D** |
| 34 | Surface labels on evening/desk | DONE | #623 | `53794d82` | books named, not merged | both briefs name Surface A; undeclared prints UNLABELED |
| 35 | morning brief earnings length | DONE | #623 | `53794d82` | verified, not rebuilt | `Earnings (D): 10 upcoming` when product.earnings=10 |
| 36 | evening cash = live temperament.cash | DONE | #623 | `53794d82` | never portfolio_implication | EOD had **no cash line at all**; now `$578,108 · 44.9%` |
| 37 | dark-contract scan | DONE | #623 | `53794d82` | no new uncalled helpers | 37 helpers / 9 modules · uncalled **2 → 0** · untested **15 → 0** |
| 38 | store_consistency never_auto_remediate | DONE | #623 | `53794d82` | regression | both findings still True; literal `False` absent from the module |
| 39 | holdings as_of vs generated_at | DONE | #623 | `53794d82` | detect only | as_of 2026-08-26 vs reprice 08-28 16:45 · **3d old** · `DATA_STALE` |
| 40 | two-writer holdings detect only | DONE | #623 | `53794d82` | **never merged** | rows **$630,784.82** vs total_cash **$578,107.50** · Δ **$52,677.32** · both printed |
| 41 | C2 TRIM non-held + **dust** blocked | DONE | #623 | `53794d82` | block **added**, nothing loosened | dust TRIM was **admitted**; now `dust_residual_not_a_position`; AVOID still admissible |
| 42 | C3 quarantine path on ingest | DONE | *(PR 4)* | *(fill after promote)* | no history scrub | hook wired at 3 call sites in `price_db_sync.py`; jsonl absent = **0 outliers**, created on first write |
| 43 | C5 critical QA dedupe key | DONE | *(PR 4)* | *(fill after promote)* | regression | dedupe in `scripts/health_agent.py` |
| 44 | rebalancer contradicted_by_cio | DONE | *(PR 4)* | *(fill after promote)* | flag only · **job still runs** | 8 AVOID symbols; annotates `cio_avoid_contradiction`, never drops or halts |
| 45 | no new Telegram producer since #611 | DONE | *(PR 4)* | *(fill after promote)* | regression | git log over the 4 producer paths since `19d1eb9e` = **0 commits** |
| 46 | INTERDICT recorded | DONE | *(PR 4)* | *(fill after promote)* | left as found | `CIO_TELEGRAM_INTERDICT=0` |
| 47 | census script | DONE | *(PR 4)* | *(fill after promote)* | read-only | `scripts/cio_wave2_census.py` recomputes the whole NOW block; agrees with the card |
| 48 | Drive upsert | **DONE (operator-run)** | *(PR 4)* | *(fill after promote)* | agent upload FAIL, no TTY | both blobs replaced; md id is capital-**O** (`…AZCqnxjOP`) — the prompt's zero 404s |
| 49 | Wave 2 closeout vs diagram | DONE | *(PR 4)* | *(fill after promote)* | docs only | `CIO_WAVE2_OVERNIGHT_CLOSEOUT.md` + `CIO_WAVE2_CENSUS_2026-08-28.json` |
| 50 | STOP | DONE | *(PR 4)* | *(fill after promote)* | **Wave 3 not started** | slices 12–41 shipped and promoted across #621 / #622 / #623 |

---

## Slice 00 live 5-line proof (pre-promote CURRENT cc2c44d3)

1. CURRENT `cc2c44d3` contains closeout; health/cio/home 200.
2. Scoreboard md+json created; Wave 1 table copied.
3. Drive folder TradeAI CIO Ops created (`1rRSmvAeO37z2PyyrIYtd2C5ngwHsAIqH`).
4. Drive file upsert FAIL — no write tool in MCP.
5. INTERDICT=0, MBI=0, notify not enabled.

---

## Slice 12 live 5-line proof (dry on CURRENT `d53fde4c`, persist=False)

1. DUST `dust_residual@v1` = aggregate market_value < $50/ticker; weight<0.5% rejected
   (would have mislabelled AMANX $5,164 and SPCX $5,458). Dust = JEPI 22.66 · LDOS 31.16 ·
   SCHG 8.09 · SRNE 0.90. **No lot deleted** — label only.
2. held_n 19 → **15**, current 15 / unavailable 0; `held_n_including_dust=19` kept visible
   so the change is auditable, not silent.
3. Three CUSIP rows (12507E201 · 543354104 · 628518102) are `instrument_id` with
   `id_type=CUSIP`, `is_ticker=false` — out of the ticker universe, out of thesis coverage.
4. `with_plan` 1 → **11**. Root cause was the counter reading the 12-row CIO NOW window
   instead of the 575-plan open store. Counter fixed; **no plan minted** to move the number.
5. 12c dry: would = BAH · CSWC · V · XAR · AMANX (cap 5, notify false, financial_action false);
   dust skipped. health/cio/home 200. MBI=0, INTERDICT=0, telegram_sent false.

---

## Slices 13 / 14 live 5-line proof (dry on CURRENT `d53fde4c`, TRADEAI_ROOT=CURRENT)

1. Identity resolves on every surface: NEW_POSITION_IF 5/5, Surface A re-entry 70/70,
   opportunity book 28/28, watch BLOCK 8/8 — **111/111 resolvable, 100%**.
2. Only NEW_POSITION_IF *stamps* the guid onto the row: **5/111 = 4.5% stamped**.
   The gap is carriage, not registry. Nothing was stamped by this slice.
3. `would_register_n = 0`. Every held non-dust ticker and active watch name is
   already registered, so **`--apply` was not run** — cap 30 never came into play.
4. Registry untouched: 10,279 entities / 5,277 symbols before and after. `minted: 0`.
5. Dry-harness trap recorded: without `TRADEAI_ROOT=CURRENT` the same command
   reports reentry 43 / watch 0 off an empty build tree. health/cio/home 200.

---

## Slices 15–18 live 5-line proof (dry on CURRENT `d53fde4c`, TRADEAI_ROOT=CURRENT)

1. graph_impact is 1-hop same-sector from the **existing** holdings sector map —
   no new store, no vendor, class D, `financial_action: false`.
2. S6 scope only: 8 open-S6 symbols, **5 attached**. SCHD 5 of 13 neighbours
   (item 72 holds), AMANX 5/13, DIV 5/11, SPCX 5/8.
3. **BND returns 0 neighbours and says so** — sole held name in Fixed Income.
   Nothing was reached for to fill the slot.
4. Three open S6 plans sit on names that are not held non-dust — CASH, QCOM,
   SRNE (dust) — skipped with an explicit reason. QCOM is a real warehouse signal.
5. Identity: `LOOKUP_FAILED` now separates an unreadable registry from a genuine
   `UNRESOLVED`; ticker-as-GUID regression locked for SCHD / CUSIP / V. Minted 0.

---

## Slices 19–21 live 5-line proof (dry on CURRENT `d53fde4c`, read-only)

1. 228 failures in the trailing 7d of 302 all time; `worker_bug_n = 0` and only
   **5 of 228 are retryable**.
2. `cost_cap` is 130 of 228 (57%) and arrives as **two** shapes — HTTP 429
   `COST_CAP_EXCEEDED` (82 all-time) and HTTP 500 `RESERVATION_FAILED` whose
   message is `COST_CAP_EXCEEDED: daily request cap` (114 all-time). The
   classifier reads the message, not the code, so the 114 are not filed as
   provider errors and nobody debugs a healthy bridge.
3. `execution_language` is 93 — output correctly refused, never requeued, and it
   blocks the plan even when a retryable truncation also exists in its history.
4. Truncated replay capped at 1 per plan per calendar day; `raises_cost_cap` is
   false on every decision. `LLM_GLOBAL_DAILY_USD_CAP` untouched.
5. Zero live model calls, zero requeues, zero rows written by this slice. The
   histogram is mtime-cached so a 9MB ledger is not re-read per home request.

---

## Slices 22–31 live 5-line proof (dry on CURRENT `d53fde4c`, no --apply)

1. Attach rule is exactly `VALID|PARTIAL` and is now stated on the payload.
   Tightening to VALID-only would silently drop **74 of 466** attachable results.
2. Live verdicts: 468 completed → VALID 392 · PARTIAL 74 · INSUFFICIENT 2 ·
   FAILED/STALE/CONFLICTED 0. `no_sources` explains 76 of the non-VALID rows.
3. **`would_attach = 2`, not 0** — `plan_5463afc7bc04` and `plan_9f4df5b991f3`
   both hold VALID completes that landed after #592's backfill. Reported, not
   applied; no slice in this batch authorises the write.
4. `resolve_due_checkpoints` due = **0**, so no `--apply` and no invented PnL.
   Binding eligibility now excludes dust: would_bind 152 → **106**, dropping
   JEPI/LDOS/SCHG/SRNE. No checkpoint deleted.
5. Lessons: 328 PROVISIONAL, all capped at REVIEW_READY, **policy count 0**.
   RESEARCH_REFERENCE 448 CANDIDATE, **0 ACTIVE**. Receipts still carry
   `memory_type` + `promotable` on everything written since 2026-08-28T13:34.

---

## Operator-authorized applies — live 5-line proof (CURRENT `5f215504`)

1. **#621 promoted** at 02:39:18Z; health/cio/home 200. Verifying the live payload
   caught that slice 12a was **not in effect**: `held_n` still 19, `with_plan` 14
   counting JEPI/LDOS/SRNE. The operator product was serving a pre-12a persisted
   brief because the freshness check only tested `held_n is None`. Fixed on PR 2.
2. **Attach (authorized):** both plans were dried, both `critique: VALID`,
   `--apply` wrote exactly 2. `would_attach` 2 → **0**, missing_result_id 254 → 252.
   The 474 were never touched.
3. **CASE_SUMMARY stayed 328** — both plans already had one from the forward path,
   and the `(symbol, plan_id, result_id)` dedup refused a second. Not a missed mint.
4. **Orphan S6 (authorized):** 20 cancelled — CASH 1, QCOM 1, and **SRNE 18**. The
   detector had been re-firing on a $0.90 residual. Cancelled, never deleted:
   `cio_plans.jsonl` 4,958 → 4,998 lines, append-only.
5. Live now: `held_n` **15**, `with_plan` **11**, `graph_impact` 5 S6 names with
   **0 skipped**, `telegram_sent` false, MBI 0, INTERDICT 0. Standing risk recorded:
   nothing yet stops the S6 detector re-creating dust plans.

---

## Slices 32–41 live 5-line proof (dry on CURRENT `5f215504`)

1. **Two cash writers disagree by $52,677.32** — position rows $630,784.82 vs
   `portfolio_totals.total_cash` $578,107.50. Both were already being shown to the
   operator in the same session with nothing saying so. Both are now printed with
   the delta; a test asserts the *average* never appears.
2. **Positions are 3 days old** (as_of 2026-08-26) under a reprice from 08-28
   16:45 — 64.8h later. Staleness is measured on the position date, so a fresh
   reprice cannot hide stale positions. `DATA_STALE`, never auto-remediated.
3. **C2 admitted "TRIM SCHG"** — 0.2294 shares is > 0, so the gate passed an
   advisory to trim $8.09 of an exited name. Now blocked
   `dust_residual_not_a_position`. AVOID on an unheld name stays admissible.
4. **complete→checkpoint is UNCOMPUTABLE**, not 0%: 523 checkpoints carry no
   `plan_id` while research keys on one. 148 are bound to CASH and 50 to dust —
   reported, not rewritten.
5. Briefs now name the Surface and the **26 watch BLOCK names** (READY stays 0,
   `fires_s7` false). Dark-contract scan: uncalled helpers **2 → 0**.
   MBI 0, INTERDICT 0, telegram_sent false.
