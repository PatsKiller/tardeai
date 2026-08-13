# Two-Way Watchlist Curation

**Status:** Implemented + schema-live + P0–P2 remediation (2026-08-13) · advisory · firewall-preserved  
**Maturity (honest):** ~6.5–7.5/10 after remediation path (forward smoke + reverse writers + scorer thesis factor + KPIs)  
**Authority:** sources `READ_ONLY_ADVISORY`; only the app role drains staging

This document records the due-diligence audit of the watch-list / proposal life cycle and the remediation that turns it from a one-way pipeline into a **closed, two-way, self-reinforcing curation loop** — CIO (Alex), the Advisory Desk, and the Defense Desk feed *into* the watch list, and realized outcomes feed *back* to re-score it.

---

## 1. Audit verdict (maturity rating)

| Dimension | Before | After |
|-----------|--------|-------|
| Forward pipeline (ingest → watchlist → proposal → risk-gated execution → outcome ledger) | 4 / 5 | 4 / 5 |
| Reverse / feedback loop (outcome → watchlist; desks → watchlist) | 1 / 5 | **4 / 5** |
| Options integration (paper outcomes → underlying conviction) | 1 / 5 | **4 / 5** |
| Instrument coverage (equity vs bond/CUSIP vs ETF/fund) | 2 / 5 | 3 / 5 |
| Autonomy / self-learning gates | 2 / 5 | 3 / 5 |
| **Overall** | **2.5 / 5** | **~3.7 / 5** |

The one-way problem: the CIO, Defense Desk, and Advisory Desk **read** the watch list and broker holdings but never **wrote back** to curation; Hermes research was not a scoring input; bonds were unresolved; and the options pipeline consumed the watch list (bullish → call, bearish → put, entry-plan → CSP strike) but its paper outcomes never fed back into it.

---

## 2. The loop (two directions)

```
FORWARD (curate in)                              REVERSE (learn back)
─────────────────────                            ─────────────────────
CIO situations  ─┐                               trade/paper outcome ──► realized_outcome + thesis_win
  (S4/S5/S8)      │                              options paper outcome ─► options_edge_score (underlying)
Advisory verdicts ├─► staging (firewall) ─►      Hermes research action ─► hermes_research_score
  (ADD/TRIM/EXIT) │     app-role drain ─►             (trade/proposal/directive_hit/none)
Defense cards    ─┘     promote_directive_lead ─► watchlist_items
  (get_into/income/short_side)
```

Every forward signal is **staged**, never written directly; the app role drains and evaluates through the same governor path as Hermes (`promote_directive_lead`). Every reverse signal updates `watchlist_items` conviction columns the scorer already reads.

---

## 3. Forward edge — desks → watchlist

### 3.1 Sources → feedback (pure mapping, `lib/two_way_curation.py`)

| Source | Signal | Directive kind | Gate |
|--------|--------|----------------|------|
| CIO `S8_DEFENSIVE_REGIME` | risk-off | `sector` + `trend` | material situations only |
| CIO `S4_SECTOR_ROTATION` | rotate targets | `sector` (or `trend`) | capped at 3 sectors |
| CIO `S5_CASH_DEPLOYMENT` | deploy candidates | `trend` | seed symbols ≤ 10 |
| Advisory `ADD`/`TRIM`/`EXIT`/`RE_ENTER` | actionable verdict | `ticker` | `evidence_count ≥ 3` + `row_class != allocation` |
| Defense `get_into` | rotate-in sector | `sector`/`ticker` | group ∈ rotate set |
| Defense `income` / `short_side` | income / hedge | `ticker` | explicit symbol |

`WAIT`/`HOLD`, thin evidence, allocation-drift rows, and `protect` cards never mint a lead.

### 3.2 Firewall (generalized from the Hermes pattern)

Each source writes **only** its own staging table; none touch `watch_directives`, `watch_directive_hits`, `watchlist_items`, or `strategy_watchpool` directly:

- `cio_directive_hits_staging`
- `advisory_directive_hits_staging`
- `defense_directive_hits_staging`

`watch_directives_service.py` drains all three via `lib.two_way_curation.drain_curation_sources()`, which mints a `watch_directives` row (deduped by `kind`+`label`, `created_by = source`) when a signal carries its own mandate, then resolves symbols and routes each through `promote_directive_lead()` under the app role. This is what makes curation **self-thinking**: desks mint their own standing directives rather than waiting for the operator.

### 3.3 Emit wiring

- `scripts/cio_heartbeat.py` — emits CIO situation feedback (shadow, fail-soft).
- `scripts/lib/advisory/advisory_opinion_engine.py` — emits actionable advisory verdicts.
- `scripts/defense_recommendations.py` — emits rotate-in / income / short-side cards.

All emit calls are **fail-soft** (a broken loop can never wedge the heartbeat) and gated behind the same non-dry-run flag as the snapshot writes.

---

## 4. Reverse edge — outcomes → watchlist

New `watchlist_items` columns (`migrations/2026-08-13_two_way_curation.sql`, additive only):

| Column | Meaning | Writer |
|--------|---------|--------|
| `realized_outcome` | `win` / `loss` / `scratch` | `hermes_outcome_grader.writeback_trade_outcomes` |
| `thesis_win` | did the thesis resolve favorably (`null` = unresolved) | same |
| `options_edge_score` | 0–100 blended IV-rank + prime-rubric edge for the underlying | `lib/options_pipeline/validation.fold_options_to_underlying` |
| `hermes_research_score` | 0–100 research-intelligence edge | `hermes_outcome_grader.writeback_hermes_research` |
| `options_edge_detail` / `hermes_research_detail` | provenance JSONB | same writers |

### 4.1 Scorer integration (`hermes_watchlist_scorer.py`)

Two new factors fold into `score_symbol`:

- `hermes_research` — weighted `0.02` (config `hermes_score_weights.yaml` v7)
- `options_edge` — weighted `0.01`

Both factors are **dropped** (not fabricated) when their column is NULL, so a symbol without Hermes research or options history simply scores without those terms. `config/hermes_score_weights.yaml` gained `graft_source: outcome_ledger` provenance.

### 4.2 Outcome verdict mapping

`hit → (win, True)` · `miss → (loss, False)` · `neutral → (scratch, None)` · anything else → skip.

### 4.3 Hermes research write-back (P1)

`grade_research_actions` already resolves each research row to `trade` / `proposal` / `directive_hit` / `none`. `writeback_hermes_research` maps that to a 0–100 score (90 / 75 / 60 / 15) and writes it onto the symbol's `watchlist_items` row — closing the previously half-wired loop where the scorer *read* the column but nothing *wrote* it.

---

## 5. Options feedback loop (P5)

`lib/options_pipeline/validation.record_outcome()` calls `fold_options_to_underlying()` after recording a paper outcome. That function:

1. Fetches a symbol's **closed** options paper outcomes.
2. Aggregates them with `options_outcomes_to_conviction()` → `{n, win_rate, net_pnl, options_edge, conviction_delta}` (delta bounded ±20 so options inform but never dominate the thesis).
3. Writes `options_edge_score` onto the **underlying** symbol's `watchlist_items` row via `write_options_edge()`.

Options remain derivatives on equity underlyings — no new `option` asset type.

---

## 6. Autonomy (P4) and coverage (P3)

- **Graduated auto-apply** is enforced live by `directive_promotion.auto_promote_allowed()` — auto only when the source tier is `core`/`trusted` **and** divergence is not `divergent`. The drain routes every desk signal through it (`auto=None` → governor decides). `lib.two_way_curation.auto_apply_gate()` adds a dry-tested **hit-rate floor** (`min_hit_rate=0.6`) as a supplementary policy primitive — it must be AND-ed with the governor, never used to bypass it.
- **Instrument class resolution** (`resolve_instrument_class`) classifies `equity` / `etf` / `bond` (9-digit CUSIP) / `cash` / `unknown`. Full bond/CUSIP resolution + advisory store unification (`protection_advisory_outcomes` vs `advisory_memory`) remain **deferred** (tracked, not blocking).

---

## 7. Audit trail

`curation_loop_audit` records provenance (`source`, `event`, `payload`) for every write: `staged` on emit, `folded` on each reverse-edge writeback. Written via `lib.two_way_curation.audit()` (fail-soft).

---

## 8. Database changes

`migrations/2026-08-13_two_way_curation.sql` — **additive only** (no DROP / rename / destructive DDL):

- 3 staging tables + partial `drained=false` indexes
- 6 reverse-edge columns on `watchlist_items` (`IF NOT EXISTS`)
- `curation_loop_audit` + index

Run `scripts/db_migrate.py` (or the project's migration runner) to apply.

---

## 9. Dry-test coverage

`tests/test_two_way_curation.py` — **40 deterministic tests**, no live DB / broker / LLM, using `FakeExecutor` / fake cursors:

| Area | Coverage |
|------|----------|
| Forward mapping (CIO/advisory/defense) | 11 tests |
| Forward emit + ensure_directive + round-trip | 5 tests |
| Forward drain (fake cursor) | 2 tests |
| Reverse outcome → ledger mapping | 4 tests |
| options edge / hermes research factor math | 4 tests |
| options outcomes aggregation (win/loss) | 2 tests |
| write options edge / hermes research / audit | 6 tests |
| P4 graduated autonomy gate | 4 tests |
| P3 instrument class resolution | 1 test |
| Scorer factor integration (P1 + P5) | 1 test |
| P5 fold round-trip | 1 test |
| P2 / P1 writeback round-trips | 2 tests |

Run:

```bash
.venv/bin/python -m pytest tests/test_two_way_curation.py -q
```

### Ops (post-remediation)

```bash
# Expand surfaced_by CHECK (cio|advisory|defense)
psql … -f migrations/2026-08-13_two_way_curation_p0_surfaced_by.sql

# Light smoke: stage synthetic S5 + optional dry drain
.venv/bin/python scripts/ops/two_way_curation_smoke.py
.venv/bin/python scripts/ops/two_way_curation_smoke.py --drain
.venv/bin/python scripts/ops/two_way_curation_smoke.py --apply-drain   # real promote

# Options reverse backfill (no-op if options_paper_outcomes empty)
.venv/bin/python scripts/ops/fold_options_edge_backfill.py

# Loop KPIs
.venv/bin/python scripts/watch_directives_monitor.py --dry-run
# GET /api/v2/watch/two-way-curation
```

Env knobs: `CURATION_DRAIN_LIMIT` (default 25), `CURATION_AUTO_APPLY_GATE=1`,  
`CURATION_AUTO_APPLY=1` + `CURATION_HIT_RATE_DEFAULT=0.65` to allow auto-apply soak.

---

## 10. Safety invariants (preserved)

- **Firewall**: sources write staging only; the app role drains and evaluates.
- **Read-only authority**: desks remain `READ_ONLY_ADVISORY`.
- **No auto-execution**: curation writes are reversible and provenance-stamped; live execution still requires operator 2FA.
- **Fail-soft loops**: every emit/fold is try/except-guarded so the loop can never wedge a heartbeat or grader.
- **Auto-blacklist on pause** and the scalp firewall remain untouched.
