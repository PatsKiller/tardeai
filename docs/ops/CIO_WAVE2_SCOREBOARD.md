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
| **cash writer NAMED** | `portfolio_totals.total_cash` is **never refreshed** — `portfolio_loader:332` carries it forward. Same field drifted $292k on 2026-07-21 and was fixed read-side only. Not a hypothesis on the list. |
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

## Cash fossil — CLOSED (2026-08-29, Saturday proof)

`portfolio_totals.total_cash` had drifted to **$578,107.50** against a
**$630,784.82** cash row sum — a **$52,677.32** gap. It was the one key in that
dict no writer refreshed.

#634 patched `portfolio_loader.load_all_portfolios`, which the pipeline never
calls. The writer that runs is `portfolio_repricer._recalc_totals` (the 16:10
Mon–Fri cron). The stored document said so — `last_pipeline_run` 08-26 from the
loader vs `last_repriced` 08-28 from the repricer — and `total_mv_excluded`
staying correct to the cent was the tell: it sits in the repricer's update list,
`total_cash` did not.

#635 (`7ad62f7b`) adds the write there. Proven the same day rather than waiting
for Monday, by running the real repricer after-hours on CURRENT:

| | before | after |
|---|---|---|
| `total_cash` | 578,107.50 | **630,784.82** |
| `cash_gap` | 52,677.32 | **0.00** |
| `temperament.cash` | 578,107.50 | **630,784.82** |
| S5 cash | `DATA_UNAVAILABLE_UNTIL_RECONCILED` | **630,784.82** |

The live payload needed the persisted brief (`cio.product.current`) rebuilt
once — it had regenerated 50s *before* the reprice, during the promote restart.
No fourth cash writer. `api_v2.py:2593` left in place. Shares unchanged.

Full evidence: `docs/ops/CIO_CASH_SATURDAY_PROOF_2026-08-29.md`.

## LLM_GATE = DONE (2026-08-29)

`ResearchNeedDecision@v2` routes every research job to one of seven outcomes —
`skip | reuse | corpus_hit | flash | pro | openai | grok_critique` — free-first,
paid only when unresolved *and* material.

Live on CURRENT, over the real open plan book:

    445 open researchable plans  ->  8 eligible model calls   (0 paid calls made)
    skip 437: not_material 353 | event_driven 38 | duplicate_same_day 35 | no_llm_kind 11

Five lines worth keeping:

1. **One freshness law.** `research_source_index.decide()` already owned
   stale/unchanged, so v2 delegates instead of keeping a second TTL opinion —
   the same two-writers-one-field shape as the `total_cash` fossil closed today.
2. **Same-day subject collapse took 43 eligible jobs to 8.** 36 open S5 cash
   plans are 36 rows asking one question.
3. **`CORPUS_UNLOCATED`.** No 20–30 publication set exists; what does is 11
   facts over 7 families in code, and only seasonality has depth.
4. **The corpus limits itself.** Only grade A/B ("independently reproduced,
   risk-modifier only") may close a gap, and never an entity-level question.
   C is context-only; D "must not be treated as a Trade AI fact".
5. **Execution language fails closed before escalation** — a tainted artifact
   never buys a bigger model. v1 `research_need_decision.py` is unchanged.

Detail: `docs/ops/CIO_LLM_GATE_CADENCE_CORPUS_2026-08-29.md`,
`docs/ops/CIO_INSTITUTIONAL_CORPUS_MAP_2026-08-29.md`.

## WAVE3A = DONE (2026-08-29) — PRs #637, #638

Seasonality series moved out of `tests/fixtures/` to
`reference/library/us_equity_monthly_synthetic_1950_2024.csv`. Same md5, same
numbers (n=75, −0.07%, 45.3%, grade=B unchanged). Not `data/` — the deploy
rsyncs with `--exclude='data/'` and `CURRENT/data/cio` is a host symlink, so a
tracked file there is never promoted.

**The move surfaced something bigger: that series is synthetic.** 1987-10 reads
+3.27% against an actual ≈ −21.5%; the worst month in 75 years is −7.88%. So
every `grade=B` "independently reproduced" seasonality label is a determinism
check of the pipeline, not empirical support for a calendar claim. Nothing was
re-graded — the move had to be number-neutral — and it is flagged for decision.

`CORPUS_UNLOCATED` is **retracted**. The 20–30 publications were catalogued all
along in `config/cio_research_source_catalog.json` (34 sources); the prior sweep
searched `data/` and filename globs, not `config/`. All 34 are `COPYRIGHT` with
no lawful full text — grade D, so none can ever `corpus_hit`. No full text
exists in repo, host data, or Drive.

`corpus_hit` now requires reproduced A/B **and** a context dimension **and** the
source index not stale. Dry unchanged: 445 → 8 eligible, 0 paid calls.

Detail: `docs/ops/CIO_WAVE3A_LIBRARY_2026-08-29.md`,
`docs/ops/CIO_LIBRARY_CENSUS_2026-08-29.md`.

## WAVE3A.3 = DONE (2026-08-29) — surface=French, synthetic=tests-only, Fed=URL+event

Operator-visible seasonality now grades off Ken French (1926–2026, real
crashes) instead of the synthetic file. Numbers moved, as required.

| effect | BEFORE (synthetic) | AFTER (French) |
|---|---|---|
| `august_general` | n=75, −0.07%, **B** | n=100, **+1.15%**, **X** |
| `september_general` | n=75, −0.20%, B | n=100, −0.77%, **B** |
| weak months | {6, 8, 9} | **{2, 9, 10}** |

**August's weak-month claim is contradicted** — grade X, "do not apply". It had
been showing `grade=B`, which reads as independently reproduced and was not.
**September survives.** **October is now weak**, which a series containing no
crash could never have shown.

Two resolvers, one rule: a determinism fixture may be synthetic, an
operator-visible number may not. `research_governance/` untouched — its
fixture is unchanged and the R1 allowlist was not edited.

Ingested: French FF5 + momentum + the normalised operator series (hashed,
grade A). Shiller and Damodaran stay URL-only — legacy `.xls` needing an
`xlrd` dep this PR does not add. Fed docs stay URL + `refresh: event`.
7 regime facts, context only, small-n rows graded C because FRED's SPX series
starts in 2016 and the window is bull-dominated.

Detail: `docs/ops/CIO_SEASONALITY_FRENCH_SURFACE_2026-08-29.md`.

## WAVE3B = schema + policy + join (2026-08-29)

notify=**SUPPRESSED** · telegram_sent=**false** · MBI=**0** · ROTATE=**advisory-only**

Three schemas, no sending. `SpecialistArtifact@v1-lite` records provider / cost
/ outcome (unknown provider raises rather than coercing — a silent normalise to
`stub` would make a paid call look free). `CIOCouncilSynthesis@v1` joins VALID
artifacts deterministically and labels disagreement **DISPUTED** with both
shown: picking a winner is the judgement that would need a model, and a
deterministic tie-break would be a fake one. `NotificationPolicy@v1` routes to
IMMEDIATE / DIGEST / COMMAND_CENTER_ONLY / SUPPRESSED — S1 observational, all
S5 cash and every duplicate subject default to SUPPRESSED; an S6 fire is
COMMAND_CENTER_ONLY, never IMMEDIATE.

Checkpoints now *declare* `plan_id`; a null is allowed when `plan_binding` says
why, because cash- and dust-bound rows have no plan by nature and are the very
rows not to be rewritten. The rate is computable over bound rows going forward.
History untouched.

EDGAR is a registry row only — entity scope, grade C, no crawler; it cannot
corpus_hit by construction.

45 tests, four of them pinning the pins. Dry unchanged: 8 eligible, 0 paid.
Detail: `docs/ops/CIO_WAVE3B_2026-08-29.md`.

## WAVE3C = receipt + lesson + registry + 1-hop (2026-08-29)

notify=**SUPPRESSED** · telegram_sent=**false** · MBI=**0** · ROTATE=advisory-only

465 delivery receipts on the live book: `none` 461, `cc` 4, **`telegram` 0**,
`WOULD SEND ANY: False`. `SUPPRESSED` maps to `none` — a suppressed decision
has no destination, not a quiet one — and `would_send` is a literal False in
the builder, never derived.

Lessons bind only to **plan-bound** checkpoints; unbound cash/dust checkpoints
mint nothing and are recorded as skipped, because "we looked and found nothing
to bind" is evidence. Hypotheses are `support_only` + `REVIEW_READY`;
`AGENT_COMMITMENT` is rejected by validate.

The spine was **extended, not duplicated**, and immediately earned it:
`stores_minting("lesson_id")` returned NONE, catching that lesson binds had
nowhere registered to live. Store added, check not softened.

1-hop graph runs for held non-dust only; CASH/dust/TEST/CUSIP are skipped **with
a reason**, never as an empty neighbour list. Found en route:
`classify_instrument_id` never returns `"ticker"` — it names CUSIP/ISIN and
returns UNKNOWN otherwise, so the first cut skipped every real ticker.

EDGAR: one fetch, one filing — Visa 10-Q filed 2026-07-29, CIK 1403161, grade C,
entity scope, cannot corpus_hit. **SCHD resolves UNAVAILABLE**: an ETF has no
issuer CIK, and guessing one would attach a fabricated identity to a real
filing.

Detail: `docs/ops/CIO_WAVE3C_2026-08-29.md`.

## WAVE3D = one hop — STOPPED at step 2, no live call made

**0 live vendor calls, $0.00, telegram_sent false.** Stopped where the brief
says to stop.

The peek offered 8 eligible, all `flash`. **Four of them — SCHD, NOC, BND,
XLI — carried a prior "execution language not allowed in research output"
failure.** The gate has always had the fail-closed law; nothing ever fed it
`prior_outcome`, so tainted plans were being offered for a paid first pass. A
guard that isn't wired to its inputs is not a guard.

Wired (`cio_research_history.py`): `execution_language_fail_closed` 0 → **11**,
eligible 8 → **4**. Setting `research_id` then broke the same-day collapse and
re-expanded S5 (35 → 1), so collapse now keys on **subject and** research_id —
restored to 35.

Step 2 returned `claimed: 0`. Nothing is claimable: **471 completed, 321
failed, 0 queued**. Step 3 was not forced: the clean candidates decide
`grok_critique`, the Grok lane is ready (OAuth proxy, free_oauth — not the
blocker), but **no live Grok critique path exists** — `research_quality.critique`
is a deterministic lint. Making the call would mean building a vendor call site,
not taking one hop through an existing one.

To run 3D: enqueue one `flash`-decision job for a clean plan, or authorise
building the critique call site as its own review.

Detail: `docs/ops/CIO_WAVE3D_2026-08-29.md`.

## WAVE3D-flash = STOPPED at step 1 — zero flash-eligible

**0 live calls, $0.00, nothing enqueued, telegram_sent false.**

SPCX decides **`grok_critique`**, not `flash` — it already has a completed VALID
artifact awaiting critique. Enqueueing it and running `--backend live` would
have called Flash on a job the gate says needs critique, which is the exact
substitution step 1 forbids. So nothing was enqueued.

Histogram over 45 open/material/non-dust/non-S5/non-TEST candidates:
`event_driven_kind_no_event` 32 · `execution_language_fail_closed` 11 ·
`grok_critique` 2 · **`flash` 0**.

Why zero: every S1/S3 candidate either has a prior VALID (→ critique, because a
paid artifact must be critiqued before attach) or a prior execution_language
failure (→ fail closed). Every S6/S7 candidate is event-driven with no event
fired, and `earnings_within(5)` is empty. The system is telling us the next
legitimate hop is **critique**, not first-pass research.

A genuine Flash job needs one of: a new material S1/S3 plan with no prior
research; a fired S6/earnings event; or a completed critique on SPCX/ARKX
(which needs 3D-critique).

Detail: `docs/ops/CIO_WAVE3D_FLASH_2026-08-29.md`.

## WAVE3D-critique = lane built, live call refused by policy

**0 vendor HTTP calls, $0.00, nothing attached, telegram_sent false.**

The missing call site now exists (`cio_grok_critique.py`), built to a contract
written first. It reuses `llm_lane.generate` — no new HTTP client — and the
curated `grok_critique` template — no new prompt. `research_quality.critique()`
still returns the deterministic lint by default; a test asserts that output is
byte-identical to before.

Stub critique of SPCX's real artifact (`res_557cfaab8c34`): VALID, no network.

The live call was **refused before reaching the proxy**: `POLICY_NOT_ALLOWED`.
**No research or critique process permits `lane=grok`** — all are DeepSeek-only
(`fast` / `deepseek-v4-flash`). 39 of 58 processes do allow grok, but none of
the critique-shaped ones, and `grok_execution_review` is manual and
semantically wrong; booking a research critique there would make the ledger
read wrong under audit.

That is the gate working. The critique failed closed: `attachable: false`,
nothing attached.

Unblocking is an operator decision: authorise `grok` on
`maria_research_critique` (free_oauth, but xAI then sees artifact text), or
critique on `deepseek-v4-flash` via `hermes_external_research` — no policy
change needed, recommended. **No policy was widened.**

Detail: `docs/ops/CIO_WAVE3D_CRITIQUE_2026-08-29.md`,
`docs/ops/CIO_GROK_CRITIQUE_CONTRACT_2026-08-29.md`.

## WAVE3E = DONE — CC block only (2026-08-29)

Scope as given: **CC block only, INTERDICT stays on, no Telegram producer.**
That made 3E pure rendering — **zero env flips**. `CIO_SITUATION_NOTIFY` stays
0, INTERDICT stays on, `telegram_sent` false, `producer` null.

Live on the real book: **466 considered → 4 surfaced** (S6: SCHD, DIV, SPCX,
BND), 0 digest, 0 immediate, **462 suppressed** — duplicate_subject 382,
not_material 72, s1_observational 7, s5_cash 1.

The suppressed histogram is on the block deliberately: showing only what fired
teaches the reader nothing else was considered. **4 is only credible next to
462.** A test asserts the four counts reconcile, and the display cap never
shrinks `surfaced_n`.

Four tests hold it to render-only — no delivery import of any kind (including
`FakeDeliveryAdapter`), no `os.environ[...] =`, `would_send: False` on every
row, no imperative. `cio_command_center.py` is CRLF; edited via safe_text_edit,
1374 → 1475 CRLF, **0 stray LF**.

Also fixed a test of mine that passed while testing nothing: blocking a policy
import needs the package *attribute* deleted, not just `sys.modules` — and an
`__import__` hook never fires for an already-imported module.

Detail: `docs/ops/CIO_WAVE3E_2026-08-29.md`.
