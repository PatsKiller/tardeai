# Two-Way Watchlist Curation

**Status:** Schema-live · production-proven · interactive desk inbox (2026-08-13) · advisory · firewall-preserved  
**Branch:** `feat/two-way-watchlist-curation`  
**Maturity (honest):** ~7.5/10 — reverse scoring live; CIO forward circulating; interactive promote inbox live; advisory/defense organic volume still ramping; options edge empty until paper outcomes exist  
**Authority:** sources `READ_ONLY_ADVISORY`; only the app role drains staging  

This document records the due-diligence audit of the watch-list / proposal life cycle and the remediation that turns it from a one-way pipeline into a **closed, two-way, self-reinforcing curation loop** — CIO (Alex), the Advisory Desk, and the Defense Desk feed *into* the watch list, and realized outcomes feed *back* to re-score it.

---

## 1. Audit verdict (maturity rating)

| Dimension | Before | After (live 2026-08-13) |
|-----------|--------|-------|
| Forward pipeline (ingest → watchlist → proposal → risk-gated execution → outcome ledger) | 4 / 5 | 4 / 5 |
| Reverse / feedback loop (outcome → watchlist; desks → watchlist) | 1 / 5 | **4.5 / 5** |
| Options integration (paper outcomes → underlying conviction) | 1 / 5 | **3 / 5** (wired; 0 rows until paper outcomes) |
| Instrument coverage (equity vs bond/CUSIP vs ETF/fund) | 2 / 5 | 3 / 5 |
| Autonomy / self-learning gates | 2 / 5 | 3.5 / 5 |
| Operator interactive surface (suggestions → one-tap promote) | 0 / 5 | **4 / 5** |
| **Overall** | **2.5 / 5** | **~3.9 / 5 (~7.5/10)** |

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

### 8.1 Core (applied)

`migrations/2026-08-13_two_way_curation.sql` — **additive only**:

- 3 staging tables + partial `drained=false` indexes  
- 6 reverse-edge columns on `watchlist_items` (`IF NOT EXISTS`)  
- `curation_loop_audit` + index  

### 8.2 Provenance (applied)

`migrations/2026-08-13_two_way_curation_p0_surfaced_by.sql` — expands  
`watch_directive_hits.surfaced_by` CHECK to:

`trade_ai | hermes | operator | cio | advisory | defense`

Desk hits no longer collapse to `hermes`.

---

## 9. Dry-test coverage

`tests/test_two_way_curation.py` — **41 deterministic tests**, no live DB / broker / LLM, using `FakeExecutor` / fake cursors:

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

### Ops (production)

```bash
# Light smoke: stage synthetic S5 + stage-only drain (safe; no Finviz)
.venv/bin/python scripts/ops/two_way_curation_smoke.py --apply-drain --stage-only

# Clear Hermes directive staging backlog (fast; stage hits only)
.venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --max 500 --stage-only
.venv/bin/python scripts/ops/drain_hermes_directive_staging.py --apply --max 100 --stage-only --touch-quiet

# Options reverse backfill (no-op if options_paper_outcomes empty)
.venv/bin/python scripts/ops/fold_options_edge_backfill.py

# Loop KPIs / ACTIVE status
.venv/bin/python scripts/watch_directives_monitor.py --dry-run

# Interactive API (portfolio server :7777)
curl -sS http://127.0.0.1:7777/api/v2/watch/two-way-curation | python3 -m json.tool | head -80
curl -sS http://127.0.0.1:7777/api/v2/watch-directives | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print('desk_suggestions', d.get('desk_suggestions_count'))"
```

Env knobs: `CURATION_DRAIN_LIMIT` (default 25), `CURATION_AUTO_APPLY_GATE=1`,  
`CURATION_AUTO_APPLY=1` + `CURATION_HIT_RATE_DEFAULT=0.65` to allow auto-apply soak.

**SM env source:** `/run/user/1000/tradeai/env` is shell-sourceable after `render_env.py`  
omits non-shell `openclaw/...` keys. Prefer:

```bash
set -a; . /run/user/1000/tradeai/env; set +a
```

---

## 11. Operator interactive surface (2026-08-13)

| Surface | Role |
|---------|------|
| **WatchpoolHub → Desk suggestions** | Inbox of `STAGED_FOR_REVIEW` hits from `cio` / `advisory` / `defense` with filter chips + **Promote** |
| `GET /api/v2/watch/two-way-curation` | Loop health + `suggestions[]` + undrained staging samples |
| `GET /api/v2/watch-directives` | Adds `desk_suggestions` / `desk_suggestions_count` (not drowned by Hermes volume) |
| `POST /api/v2/watch/directives/promote` | Operator one-tap; `auto=True` override; scalp firewall still applies |

Promote remains **advisory** (watchlist / watchpool registration) — never orders / 2FA.

### Emit wiring (forward)

| Source | Module | Notes |
|--------|--------|-------|
| CIO | `cio_reactive_cycle.py` | New plans + **open S4/S5/S8** re-seed (rate-limited) |
| Advisory | `advisory_opinion_engine.emit_watchlist_feedback` | Also on **cache hit** (no longer starved); ADD/RE_ENTER need evidence ≥ 2; TRIM/EXIT ≥ 3 |
| Defense | `defense_recommendations.py` | `get_into` / `income` / `short_side` only |

### Reverse wiring

| Writer | Columns | Scorer factor |
|--------|---------|---------------|
| Outcome grader via lib writers | `realized_outcome`, `thesis_win` | `thesis_outcome` (weights v8) |
| Outcome grader | `hermes_research_score` | `hermes_research` |
| Options `fold_options_to_underlying` | `options_edge_score` | `options_edge` |

---

## 12. Live verification snapshot (2026-08-13)

| Signal | Value |
|--------|------:|
| Monitor status | **ACTIVE** |
| Hermes staging undrained | **0** (after fast drain) |
| Desk suggestions (API) | **9** CIO staged (SCHD/VTI/XLU family) |
| Desk hits 24h | **cio ≥ 9** honest `surfaced_by` |
| Reverse: hermes_research / realized / options | **1115 / 111 / 0** |
| Audit trail 24h | **~18k** (research + outcome + cio) |
| Unit tests | **41 passed** |

---

## 13. Safety invariants (preserved)

- **Firewall**: sources write staging only; the app role drains and evaluates.
- **Read-only authority**: desks remain `READ_ONLY_ADVISORY`.
- **No auto-execution**: curation writes are reversible and provenance-stamped; live execution still requires operator 2FA.
- **Fail-soft loops**: every emit/fold is try/except-guarded so the loop can never wedge a heartbeat or grader.
- **Auto-blacklist on pause** and the scalp firewall remain untouched.
- **Stage-only drain** available for backlog clear without Finviz lock storms.

---

## 14. Key commits (branch `feat/two-way-watchlist-curation`)

| Commit | Summary |
|--------|---------|
| `b2e451f1` / `a971f9a5` | Initial two-way loop + reactive emit |
| `30d3e05d` | SM env shell-sourceable (skip `openclaw/...` keys) |
| `c1d9046a` | P0–P2: provenance, reverse writers, scorer, KPIs |
| `bfc8f674` | Fast Hermes staging drain |
| `67946947` | Interactive desk suggestions + promote UI/API |
