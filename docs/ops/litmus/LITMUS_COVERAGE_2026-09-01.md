Status:      ACTIVE  
as_of:       2026-09-01T15:29:00-04:00  
Measured at: CURRENT BUILD_SHA `18a3da0dc` (file content) · dir `18a3da0dc-main-exact-phase2-20260901-143119`  
             origin/main `ac4b37cea` · worktree HEAD `576a8c7c0` · $PROJ hub `0a591048b`  
Canonical repo path: docs/ops/litmus/LITMUS_COVERAGE_2026-09-01.md  
Authority:   discovery only. No product change. No minting. No pack.  
See also:    docs/maturity/CIO_INVESTMENT_PRODUCT.md (RE_ENTER rule)  
             docs/architecture/CIO_ASIS_VS_SPEC_2026-08-30.md (MATERIALITY S1–S7)  
             docs/cio/SITUATIONS.md · docs/ops/litmus/LITMUS_HOLDINGS_CLOCKS_2026-09-01.md

# Litmus · D coverage (holdings vs plans vs watch vs re-entry vs S3)

## Pre-flight (quoted before write)

```
worktree      /home/johnclaw/tradeai-wt-final-operator-convergence  HEAD 576a8c7c0
origin/main   ac4b37cea
CURRENT       BUILD_SHA 18a3da0dc · SOURCE_COMMIT 18a3da0dc
$PROJ         crontab PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
              hub HEAD 0a591048b  ≠  origin/main ac4b37cea  → reported; measured CURRENT only
```

**Twin search:** open PRs matching `LITMUS_COVERAGE` — **none**.  
`LITMUS_HOLDINGS_CLOCKS` / `LITMUS_MONEY` exist — different slices (clocks / cash totals).

**No minting.** `identity_coverage.mint=false` · `minted=0` on the live brief. This file only names what already exists in stores.

---

## RE_ENTER rule (quoted)

From `docs/maturity/CIO_INVESTMENT_PRODUCT.md` and CURRENT `scripts/lib/cio_investment_product.py`:

> Desk `IN_ZONE` / `READY` / `NEAR` is **WAIT/NEAR**, never auto `RE_ENTER`.  
> A candidate-specific governed `RE_ENTER` is written only when the opportunity queue already carries `verdict=RE_ENTER`, **or** zone-ready + explicit `ADD` + valid Financial Senses + no restricting lesson **and** lesson influence is `CANARY` or `ACTIVE_ADVISORY`.

Live check on CURRENT stores:

| surface | path | RE_ENTER signal | verdict |
|---|---|---|---|
| governed verdicts | `data/cio/cio_governed_verdicts.json` | `verdicts=[]` · as_of 2026-09-01T19:24:25Z | **EMPTY** — no candidate-specific RE_ENTER |
| investment brief | `cio_investment_brief.json` → `governed_verdicts` | `[]` | **EMPTY** |
| action book | `action_book.DO_NOW` | `[]` | **no DO_NOW RE_ENTER** |
| action book | `action_book.RE_ENTER_IF` | 56 rows (NEAR/WAIT upstream → IF) | **conditional only** — not governed RE_ENTER |
| re-entry book | `reentry_book.names[*].governed_verdict` | all `None` (70/70) | **rule holds** — desk status ≠ RE_ENTER |
| reentry payload | `reentry_payload_last.json` | actions READY=6 · NEAR=55 · no RE_ENTER | **desk zone only** |

**Finding:** RE_ENTER rule is holding. Desk READY/NEAR/IN_ZONE populate books and S3 plans; they do **not** mint governed `RE_ENTER`.

---

## AS-IS MATERIALITY S1–S7 (catalog vs live open plans)

Catalog authority: `docs/cio/SITUATIONS.md` · AS-IS node `█ MATERIALITY S1–S7` in `CIO_ASIS_VS_SPEC_2026-08-30.md` (dated; re-measured here).

Store: `persistent-state/data/cio/cio_plans_projection.json` (CURRENT `data/cio` → same) · `updated_ts=2026-09-01T17:26:26Z` · **1138** plans · **494** open (`draft|proposed`; **0** `accepted`).

| code | name | open plans | unique symbols on open | ∩ held equity (19 tickers) | note |
|---|---|---|---:|---:|---|
| **S1** | POSITION_LIFECYCLE | 7 | 7 | **7** — ARKX BND NOC SCHD SPCX XLB XLI | live on a subset of book |
| **S2** | STOP_GAP | 0 | 0 | 0 | dark this measure |
| **S3** | REENTRY_CANDIDATE | **378** | 60 | **0** | former/watch candidates — **not** current holdings |
| **S4** | SECTOR_ROTATION | 0 | 0 | 0 | dark this measure (1 cancelled historically) |
| **S5** | CASH_DEPLOYMENT | 42 | 0 (`symbols=[]`) | n/a — book-level cash | all fire `cash_pct_above_band` + `quality_PARTIAL` |
| **S6** | CONCENTRATION_OR_DISPOSITION | 53 | 6 | **6** — AMANX BND DIV NOC SCHD SPCX | live |
| **S7** | WATCH_PROMOTION | 8 | 6 | **0** | DXCM SMCI FTH ABUS ACN FATN — not held |
| S0 | OPERATOR_CONVERSE | 6 | 1 | 1 (SCHD) | not in S1–S7 materiality set |
| S8 | DEFENSIVE_REGIME | 0 | 0 | 0 | absent from open set |

**Position-coverage definition** (open S1/S3/S5/S6 on a held ticker — Wave-2 slice language): **9 / 19** equity tickers covered · **13 uncovered** (see named section). S3 does **not** help position coverage: intersection with held equity is empty by design (re-entry = former/watch).

---

## Holdings vs plans vs watch vs re-entry (matrix)

Holdings store: `persistent-state/data/portfolios/state/holdings.json` · `data_as_of=2026-09-01` · `n_holdings=29` rows · accounts with live rows: `alpaca_taxable_live` · `schwab_taxable` · `schwab_roth` · `schwab_rollover_ira`.

| population | count | source |
|---|---:|---|
| holding rows | 29 | holdings.json |
| unique symbols incl CASH + CUSIP-as-symbol | 23 | — |
| equity tickers (excl CASH + 3 CUSIPs) | 19 | — |
| of which dust (`MV < $50` aggregate) | 4 — JEPI LDOS **SCHG** SRNE | brief `holdings_thesis_coverage.dust_tickers` |
| thesis CURRENT holdings | 15 | brief `held_n` / `items` |
| open plans any S-class on held equity | 9 tickers | plans projection |
| watchlist.json keys | 13 | no SCHG / CASH / CUSIP |
| ai_watchlist candidates | 54 | includes SCHG + CASH |
| reentry desk rows | 106 | `reentry_decision_desk_latest.json` · computed_at 2026-09-01T19:26:35Z |
| reentry_payload_last | 61 (READY 6 / NEAR 55) | ∩ held equity = **∅** |
| reentry_book names | 70 (NEAR 26 / WAIT 30 / AVOID 14) | former holdings surface A |
| governed RE_ENTER | 0 | — |

```
HELD equity ──S1/S6──► subset covered (9)
         ──S3──► no overlap (S3 is re-entry universe)
         ──S7──► no overlap (watch promotion)
         ──watchlist.json──► mostly non-overlap (13 research names)
         ──ai_watchlist──► partial (held names appear as candidates, incl dust SCHG)
         ──reentry desk/payload/book──► former/watch; not current book
CASH ──S5──► 42 open book-level plans (symbols=[]) · action_book.HOLD_CASH_FOR
CUSIP-as-symbol ──plans/watch/reentry──► ABSENT everywhere except holdings + brief instrument_ids
moomoo_taxable_live ──holdings rows──► 0 · account_summaries.retired=true
```

---

## Named symbols

### SCHG

| surface | presence | detail |
|---|---|---|
| holdings | **YES** | `schwab_taxable` · MV **$8.09** · 0.2294 sh · classified **DUST_RESIDUAL** |
| open plans | **NO** | only `plan_240454cce9cc` **cancelled** S1 (2026-08-29) |
| watchlist.json | **NO** | — |
| ai_watchlist | **YES** | candidate · score 8 · `last_seen` 2026-08-26 · bucket research_queue |
| reentry payload / desk / book | **NO** | — |
| brief thesis items | **NO** (dust path) | listed under `dust_tickers` · `thesis_status=NOT_REQUIRED` |
| action_book CURRENT_HOLDINGS_THESIS | **YES** | named in the 19-symbol carriage list |

### CUSIP (three delisted rows carried as symbol)

| instrument_id | account | shares | MV | name on row | plans | watch | re-entry |
|---|---|---:|---:|---|---|---|---|
| **12507E201** | schwab_taxable | 7 | 0 | DELISTED — CUSIP 12507E201 | none | none | none |
| **543354104** | schwab_rollover_ira | 3000 | 0 | DELISTED — CUSIP 543354104 | none | none | none |
| **628518102** | schwab_rollover_ira | 125 | 0 | DELISTED — CUSIP 628518102 · config revoked as MYGO Games Hldg | none | none | none |

Brief `holdings_thesis_coverage.instrument_ids` stamps all three as `id_type=CUSIP` · `is_ticker=false` · class D. **No ticker mint** — they stay CUSIP-shaped symbols in the holdings document.

### CASH

| surface | presence | detail |
|---|---|---|
| holdings | **YES** ×4 accounts | alpaca $5,000 · schwab_taxable $37,900.86 · schwab_roth $1,559.99 · schwab_rollover_ira $586,052.77 · **sum $630,513.62** |
| S5 plans | **YES** (book-level) | 42 open · `symbols=[]` · hold_cash / stage |
| action_book | **YES** | `HOLD_CASH_FOR` · cash_pct **49.35** · band hi 20 · quality OK |
| open S1/S3/S6 symbol lists | **NO** | one historical cancelled S6 named CASH |
| watchlist.json | **NO** | — |
| ai_watchlist | **YES** | candidate (anomalous — cash as research_queue row) · last_seen 2026-07-27 |
| reentry surfaces | **NO** | CASH is not a re-entry candidate |

### Retired Moomoo

| surface | presence | detail |
|---|---|---|
| holdings rows | **ABSENT** | 0 rows with `account=moomoo_taxable_live` |
| account_summaries | **YES · retired** | `retired=true` · `retired_at=2026-09-01` · reason: account closed; feed dead since 2026-08-03 · holdings_count=0 · total_value=0 |
| archive | **YES** | `trade-ai-releases/holdings-moomoo-retire-20260901-131731/RETIRED_moomoo_taxable_live.json` · schema `RetiredAccountRow@v1` · archived prior CASH $500 row · tripwire if anything re-reads the live account |
| plans / watch / re-entry | **no moomoo account key** | symbols may exist elsewhere; the **account** is retired |

---

## S3 specifically

- Catalog: **S3 = REENTRY_CANDIDATE** — reads re-entry decision desk READY/NEAR; does not re-rank.
- Live: **378 open** S3 plans · **60** unique symbols · sample ACHV ADBE AIRE … (former/watch universe).
- **∩ held equity = ∅.** S3 is not position coverage for the current book.
- Desk payload READY names this measure: ACHV ARKQ CAST MOGU PETS TSLA — all non-held.
- Brief `reentry_book` (Surface A, former holdings vs exit trigger): 70 names · statuses NEAR/WAIT/AVOID only · **governed_verdict all None** · entry_trigger text still requires "governed RE_ENTER + non-stale confirmation".

S3 volume ≠ RE_ENTER authority. Large open-S3 count is consistent with desk NEAR/READY fan-out under the RE_ENTER rule (WAIT/NEAR, not auto promote).

---

## Uncovered held equity (open S1/S3/S5/S6)

```
12507E201  543354104  628518102   ← CUSIP / delisted (not expected on S-plans)
BAH  CSWC  JEPI  LDOS  PFLT  RTX  SCHG  SRNE  V  XAR
```

Of these, JEPI / LDOS / SCHG / SRNE are **dust** under brief policy (`<$50` aggregate MV). Residual real-book gaps vs open material plans: **BAH CSWC PFLT RTX V XAR** (+ the three CUSIPs).

---

## What this slice does not claim

No product fix · no plan mint · no identity mint · no `$PROJ` fast-forward · no promote · no choice of which uncovered name should get an S1 · no pack.

**STOP.** Discovery only.
)
