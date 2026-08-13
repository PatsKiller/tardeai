# Phase 5 — Mature the two-way Watch / Defense / Rotation / Re-Entry loop

> Goal (from the convergence prompt): complete the institutional idea lifecycle so
> the office finds replacements and future opportunities without operator
> scavenger hunts. Everything stays `READ_ONLY_ADVISORY` — no execution authority.

## 1. Scope

Phase 5 matures the loop that Phase 3–4 wired and that the earlier two-way
curation track (`scripts/lib/two_way_curation.py`, migration
`2026-08-13_two_way_curation.sql`) already foundations. Two directions:

```
FORWARD  CIO/Advisory/Defense/Rotation/Re-Entry → staging firewall
         → governed directive/promote path → Watch Intelligence
         → research / review / trigger state → proposal-eligible advisory state

REVERSE  operator disposition · trade/paper outcome · re-entry outcome
         · Hermes research quality · options evidence · missed opportunity
         · thesis outcome → scored learning inputs → Watch ranking / calibration
```

## 2. Foundation already in place

| Concern | Where | State |
| --- | --- | --- |
| Forward staging firewall (CIO/Advisory/Defense) | `cio_/advisory_/defense_directive_hits_staging` + `drain_curation_sources` | **live** |
| Governed promote path (no bulk bypass) | `drain_curation_sources` → `promote_directive_lead` governor + `auto_apply_gate` | **live** |
| Reverse edge: trade outcome | `write_realized_outcome` (realized_outcome + thesis_win) | **live** |
| Reverse edge: options outcome | `write_options_edge` + `fold_options_to_underlying` | **live** |
| Reverse edge: Hermes research | `write_hermes_research` + `hermes_research_score_from_action` | **live** |
| Provenance audit | `curation_loop_audit` + `audit()` on every fold | **live** |
| Scorer reverse factors | `hermes_watchlist_scorer._f_hermes_research/_f_options_edge/_f_thesis_outcome` | **live** |

## 3. Gap analysis (requirements → status)

1. **Preserve source provenance** — `SOURCES` covers `cio/advisory/defense` plus
   `operator/trade_ai/hermes` in `DESK_PROMOTION_TIER`. **`rotation` and `reentry`
   are not yet first-class sources** — they flow indirectly via CIO S4 / advisory
   RE_ENTER. GAP: add `rotation`/`reentry` provenance.
2. **Bulk staging must not bypass promotion governance** — SATISFIED (single
   governor brain; `auto_apply_gate` requires trusted tier + non-divergent +
   hit-rate floor).
3. **Lock/contention under full promote load** — NOT ADDRESSED (needs load test).
4. **Do not inflate reverse-learning weights before calibration** — SATISFIED.
   `calibrate_reverse_weight` / `calibrate_reverse_weights` gate every reverse factor
   by `n / n_min`, so effective weight can never exceed the base (§4).
5. **Label proxy vs realized distinctly** — SATISFIED. `evidence_class_for` +
   the `options_edge` `evidence_class` detail field label each reverse signal
   `realized` vs `proxy` (§4).
6. **Add sample-size/reliability fields to reverse factors** — SATISFIED. `*_n`
   columns + `_reverse_reliability` metadata on the scorer intel card (§4b).
7. **"Desk suggestions" → Alex opportunity queue** — NOT ADDRESSED.
8. **Sector opportunity behavior** — NOT ADDRESSED (see §6).

## 4. Delivered — reverse-factor reliability, calibration, sample-size `n`, and scorer wiring

### 4a. Pure reliability gate (`scripts/lib/two_way_curation.py`, increment 1)

- `evidence_class_for(factor, *, override)` — labels a reverse factor `realized`
  (graded against an outcome) vs `proxy` (IV rank / queue edge / research intent).
  Unknown factors default to `proxy` (fail-safe: never assume an unclassified
  signal is realized).
- `reverse_factor_reliability(factor, n, *, evidence_class)` — reliability ramps
  linearly `n / n_min` capped at 1.0; `n` of `None/0/negative` → 0.0 (drop the
  factor, never fabricate a neutral). Returns `trusted = (n >= n_min)` and a
  distinct `label` embedding the evidence class.
- `calibrated_reverse_weight(base, factor, n, *)` — `effective = base * reliability`,
  so effective weight can **never exceed** the configured base.
- `calibrate_reverse_weights(base_weights, sample_sizes, *)` — applies the gate to
  a whole reverse-weight map and reports `all_trusted`.
- `REVERSE_FACTORS = ("thesis_outcome", "options_edge", "hermes_research")` — the
  single source of truth the scorer reads.

`n_min` defaults: `thesis_outcome=3`, `options_edge=5`, `hermes_research=5`.

### 4b. Sample-size `n` persistence + scorer wiring (increment 2 — this change)

- **Schema** (`migrations/2026-08-13_two_way_reliability_n.sql`, additive):
  `watchlist_items.thesis_outcome_n`, `options_edge_n`, `hermes_research_n` INTEGER.
- **Writers** now accept and persist `n` (and `evidence_class` for options):
  - `write_realized_outcome(..., n=)` → `thesis_outcome_n`
  - `write_options_edge(..., n=, evidence_class=)` → `options_edge_n` + `evidence_class` in detail
  - `write_hermes_research(..., n=)` → `hermes_research_n`
  Each uses `COALESCE(%s, <col>)` so a missing `n` preserves the prior sample count
  (never an accidental zero-out). `symbol` remains the last positional param; `score`
  stays first in the research writer (back-compat).
- **Callers aggregate `n` per symbol**:
  - `hermes_outcome_grader.writeback_trade_outcomes` / `writeback_hermes_research`
    now group by symbol and pass `n = len(verdicts)`, latest-graded wins.
  - `options_pipeline.validation.fold_options_to_underlying` threads `n` (closed
    outcomes = realized, approval-queue = proxy) + `evidence_class` into
    `write_options_edge`.
- **Scorer** (`hermes_watchlist_scorer.score_symbol`) reliability-gates every reverse
  factor before blending: `eff_weight = base * reliability`; a factor at `n=0`/unknown
  is damped to zero and dropped from the blend/coverage, a below-`n_min` factor is
  partially damped, an `n≥n_min` factor is full weight. Emits `_reverse_reliability`
  metadata (reliability / n / n_min / evidence_class / trusted) on the intel card.
  `_BASE_SELECT` + the off-hours select now fetch the three `_n` columns.

Canaries:
- `tests/test_two_way_reliability.py` (13 tests) — pure gate: ramp linearity,
  never-exceeds-one, None/negative/invalid → 0, unknown-factor default, evidence-class
  defaults + override, realized-vs-proxy label distinction, weight-never-inflated,
  full-weight-at-n_min, zero-below-min, map calibration, missing-sample → drop,
  all-trusted.
- `tests/test_two_way_curation.py` (+10 tests) — `n` persistence on all three writers
  (param slot + symbol-last invariant), per-symbol aggregation in both writebacks,
  scorer damp-below-n_min / full-at-n_min / missing-n → zero, and the fold path
  passing `n` + `evidence_class` (closed = realized).

```bash
python3 -m pytest tests/test_two_way_reliability.py tests/test_two_way_curation.py -q
```

## 5. Next increments (in order)

1. **`rotation` / `reentry` first-class sources.** Add staging tables + `SURFACED_BY`
   entries + drain inclusion so their provenance is preserved end-to-end.
2. **Desk suggestions → Alex opportunity queue.** A single Alex-consumable surface
   (not a page the operator monitors all day) fed by staged/undrained curation.
3. **Sector opportunity behavior** (§6) — Alex's "Sector X is improving…" synthesis.
4. **Lock/contention remediation** under full promote load (benchmark + fix).

## 6. Required sector opportunity behavior (Checkpoint 5 target)

When Rotation/Defense detects a material sector shift, Alex must be able to state:

> Sector X is improving. Current portfolio exposure = Y%. Policy/target posture =
> Z%. Potential incremental capital = $A. Best current candidates = B/C/D. B is
> Watch READY, C needs research, D is too extended. I recommend no deployment /
> staged deployment / research first.

This is the acceptance shape for the sector-opportunity synthesis (increment 3).

## 7. Checkpoint 5

Prove one full **organic** loop — no synthetic shortcut counts:

```
sector/defense or CIO event → staged Watch idea → research → Watch state change
→ Alex decision → operator disposition → reverse evidence recorded
```

## 8. Known gaps (honest, not hidden)

- The reliability gate + `n` persistence are wired; the gate is only as good as the
  `n` writers produce — a backfill is not yet run, so existing rows have `_n = NULL`
  (damped to zero) until the outcome graders / options fold run and populate them.
- `rotation`/`reentry` provenance, the Alex opportunity queue, sector-opportunity
  synthesis, and load lock/contention are unimplemented (increments 1–4).
- Checkpoint 5 (organic loop) has not been run; it requires live data flow.
