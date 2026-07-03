# Hermes Closed-Loop Traceability — Master Roadmap & Validation

**Status:** Live (2026-07-03) · Prompts 1–3 implemented on `main`

## Master roadmap (Prompts 1–3)

| Prompt | Scope | Status | Key artifacts |
|--------|-------|--------|---------------|
| **1 — Watchlist** | Health + lifecycle + stop quality + governor gate | **Done** | `watchlist_health.py`, `watchlist_lifecycle.py`, `cac9949e`, stop weight 25% |
| **2 — Holdings** | Health + lifecycle + research depth | **Done** | `holdings_lifecycle.py`, `research_scheduler.py` T0 multipliers, `712f21ed` |
| **3 — Feedback loops** | Stop reactions, bus export, evaluation, traceability | **Done** | `reactions.py`, `lifecycle_slice.py`, Phase D eval, `symbol_journey.py` |

### End-to-end linkage

```
watchlist_items.scope_tier
        ↓
Scope Governor (edge + health gate + bus reactions)
        ↓
watchlist_lifecycle.json + scope_governor_audit
        ↓
research_scheduler (tag + holdings multipliers)
        ↓
trades / hermes_outcome_ledger
        ↓
outcome_bus.json (nightly) + lifecycle slice
        ↓
watchlist/holdings health refresh + threshold learner + --evaluate
```

## Symbol journey API (traceability)

**GET** `/api/v2/hermes/symbol-journey?symbol=XYZ`

Returns merged timeline from:

- `scope_governor_audit` — tier changes
- `hermes_watchlist_lifecycle_audit` — blocks, overrides
- `hermes_outcome_ledger` — graded outcomes
- `paper_trades` — recent positions
- `outcome_bus.by_symbol` + `lifecycle.*` snapshots

**UI:** `/v3/hermes` → Closed Loop — click any watchlist, holdings, or bus symbol row.

## Combined validation checklist

Run after deploy or weekly during observation window:

### Prompt 1 — Watchlist

1. `hermes_scope_governor.py --dry-run` — weak-health high-edge symbols in `blocked_promotions`, not in S1 `want` claims
2. `hermes_watchlist_lifecycle.json` — `health_score`, `health_components`, `health_history` per symbol
3. Closed Loop — Health column + 7d trend + **watch** stage
4. `pytest tests/test_watchlist_lifecycle.py -q` — all pass

### Prompt 2 — Holdings

5. `GET /api/v2/hermes/holdings-lifecycle` — `panel_rows` with health + monitoring hints
6. Holdings **watch** / **trim_candidate** rows visible in Closed Loop
7. `research_scheduler.py --mode holdings --dry-run` — T0-HOLD symbols get elevated priority when stage ≠ healthy
8. `pytest tests/test_holdings_lifecycle.py -q` — all pass

### Prompt 3 — Feedback & traceability

9. `hermes_outcome_feedback_agent.py --apply` — `outcome_bus.json` contains `lifecycle.watchlist` + `lifecycle.holdings`
10. Governor dry-run with bus — `stop_quality_*` reactions in `bus_reactions` when divergence/R-left triggers fire
11. `hermes_threshold_learner.py --evaluate` — threshold evals + `closed_loop` promotion-gate verdict
12. `GET /api/v2/hermes/symbol-journey?symbol=SCHD` — `timeline` with governor + outcome events
13. Proposal history in Closed Loop shows `evaluation_outcome` when `--evaluate` has run
14. `pytest tests/test_symbol_journey.py tests/test_lifecycle_bus_slice.py tests/test_closed_loop_evaluation.py -q`

### Audit surfaces

| Event | Log |
|-------|-----|
| Tier change | `scope_governor_audit` |
| Bus reaction | `scope_governor_audit` (`__BUS__`) + `hermes_bus_reactions.json` |
| Watchlist lifecycle | `hermes_watchlist_lifecycle_audit.jsonl` |
| Blocked promotion | `blocked_promotion` rows in lifecycle audit |
| Threshold change | `hermes_threshold_audit.jsonl` |
| Gate evaluation | `hermes_closed_loop_evaluations.json` |

## Example scenario — full trace

1. **XYZ** on S2, edge 68, health 54 → governor **blocks** S1 promotion (`blocked_promotion` audit)
2. Nightly bus grades XYZ promotion history → `by_symbol.gate = demote_pressure`
3. Watchlist lifecycle → stage **watch**, health trend ↓
4. `--evaluate` → `closed_loop.verdict = helped` (blocked symbols had low promo hit rate)
5. Operator clicks **XYZ** in Closed Loop → `symbol-journey` timeline shows block → gate → stage in order

## Related docs

- `HERMES_WATCHLIST_LIFECYCLE.md`
- `HERMES_HOLDINGS_LIFECYCLE.md`
- `HERMES_SCOPE_GOVERNOR.md` (stop-quality reactions table)
- `OUTCOME_BUS_IMPLEMENTATION.md`
- `HERMES_THRESHOLD_EVALUATION_ENGINE.md`