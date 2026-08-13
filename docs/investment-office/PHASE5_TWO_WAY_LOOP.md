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
4. **Do not inflate reverse-learning weights before calibration** — PARTIAL.
   Weights are already tiny (`hermes_research 0.02`, `options_edge 0.01`), but there
   was no explicit sample-size gate. **Delivered this phase (§4).**
5. **Label proxy vs realized distinctly** — PARTIAL. `blend_options_edge_sources`
   already orders closed (realized) > queue > IV-only (proxy), but the label was
   implicit. **Delivered explicit `evidence_class` this phase (§4).**
6. **Add sample-size/reliability fields to reverse factors** — PARTIAL. The pure
   gate exists now (§4); the schema columns + scorer wiring are the next step (§5).
7. **"Desk suggestions" → Alex opportunity queue** — NOT ADDRESSED.
8. **Sector opportunity behavior** — NOT ADDRESSED (see §6).

## 4. Delivered this phase — reverse-factor reliability & calibration gate

`scripts/lib/two_way_curation.py` gains a pure, no-I/O reliability gate (Phase 5
increment 1):

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

`n_min` defaults: `thesis_outcome=3`, `options_edge=5`, `hermes_research=5`.

Canaries: `tests/test_two_way_reliability.py` (13 tests) — ramp linearity,
never-exceeds-one, None/negative/invalid → 0, unknown-factor default, evidence-class
defaults + override, realized-vs-proxy label distinction, weight-never-inflated,
full-weight-at-n_min, zero-below-min, map calibration, missing-sample → drop,
all-trusted. Run:

```bash
python3 -m pytest tests/test_two_way_reliability.py tests/test_two_way_curation.py -q
```

## 5. Next increments (in order)

1. **Sample-size schema + scorer wiring.** Persist `n` per reverse factor (either
   new `watchlist_items` columns `thesis_outcome_n`, `options_edge_n`,
   `hermes_research_n`, or the existing `*_detail` JSONB) and have
   `hermes_watchlist_scorer` call `calibrate_reverse_weights` so a below-`n_min`
   factor is damped. `options_outcomes_to_conviction` already computes `n`; thread
   it through `write_options_edge`/`write_hermes_research` detail payloads.
2. **`rotation` / `reentry` first-class sources.** Add staging tables + `SURFACED_BY`
   entries + drain inclusion so their provenance is preserved end-to-end.
3. **Desk suggestions → Alex opportunity queue.** A single Alex-consumable surface
   (not a page the operator monitors all day) fed by staged/undrained curation.
4. **Sector opportunity behavior** (§6) — Alex's "Sector X is improving…" synthesis.
5. **Lock/contention remediation** under full promote load (benchmark + fix).

## 6. Required sector opportunity behavior (Checkpoint 5 target)

When Rotation/Defense detects a material sector shift, Alex must be able to state:

> Sector X is improving. Current portfolio exposure = Y%. Policy/target posture =
> Z%. Potential incremental capital = $A. Best current candidates = B/C/D. B is
> Watch READY, C needs research, D is too extended. I recommend no deployment /
> staged deployment / research first.

This is the acceptance shape for the sector-opportunity synthesis (increment 4).

## 7. Checkpoint 5

Prove one full **organic** loop — no synthetic shortcut counts:

```
sector/defense or CIO event → staged Watch idea → research → Watch state change
→ Alex decision → operator disposition → reverse evidence recorded
```

## 8. Known gaps (honest, not hidden)

- The reliability gate is pure logic; it is **not yet wired into the live scorer**
  until sample-size `n` is persisted (increment 1). Until then the tiny base
  weights remain the only inflation guard.
- `rotation`/`reentry` provenance, the Alex opportunity queue, sector-opportunity
  synthesis, and load lock/contention are unimplemented (increments 2–5).
- Checkpoint 5 (organic loop) has not been run; it requires live data flow.
