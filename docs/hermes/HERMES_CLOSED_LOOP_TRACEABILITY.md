# Hermes Closed-Loop Traceability — Master Roadmap & Validation

**Status:** Live (2026-07-05) · Prompts 1–3 + bus traceability + **maturity hardening** on `main`

## Master roadmap (Prompts 1–3)

| Prompt | Scope | Status | Key artifacts |
|--------|-------|--------|---------------|
| **1 — Watchlist** | Health + lifecycle + stop quality + governor gate | **Done** | `watchlist_health.py`, `watchlist_lifecycle.py`, `cac9949e`, stop weight 25% |
| **2 — Holdings** | Health + lifecycle + research depth | **Done** | `holdings_lifecycle.py`, `research_scheduler.py` T0 multipliers, `712f21ed` |
| **3 — Feedback loops** | Stop reactions, bus export, evaluation, traceability | **Done** | `reactions.py`, `lifecycle_slice.py`, `bus_traceability.py`, Phase D eval, `symbol_journey.py` |
| **4 — UI polish** | Symbol journey timeline, proposal impact narratives | **Done** | `SymbolJourneyPanel.tsx` (`3ec93b08`), `proposal_impact.py` (`a0fb8bac`) |
| **5 — Stop quality ↔ watchlist** | Health weight 25%, research mult, degrading UI | **Done** | `watchlist_research_multiplier`, Closed Loop stop watch rows |
| **6 — Maturity hardening** | Scorecard, evidence gates, counterfactuals, do-no-harm, governance | **Done** | `scorecard.py`, `evidence_gates.py`, `do_no_harm.py`, `governance.py` (2026-07-05) |

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
outcome_bus.json (nightly)
  ├── lifecycle.* (compact)
  ├── watchlist_health / holdings_health (full scores + history)
  ├── threshold_proposals (bus snapshot linkage)
  └── lineage.snapshot_id + by_symbol.lineage
        ↓
watchlist/holdings health refresh + threshold learner + --evaluate
```

## Outcome bus traceability (nightly `--apply`)

Module: `scripts/lib/hermes_outcome_bus/bus_traceability.py`

| Section | Contents |
|---------|----------|
| `lineage` | `snapshot_id`, `prior_run_id`, upstream/downstream |
| `watchlist_health` | Per-symbol health score, 6 components, `health_history`, `data_quality` |
| `holdings_health` | Per-holding health, stop quality snapshot, lifecycle stage, history |
| `threshold_proposals` | Pending + recent decided with `metrics_at_snapshot`, prior proposal chain |
| `stop_quality.trends` | 7d/14d deltas (trail, alignment, R-left, tier alignment) |
| `by_symbol.*.lineage` | Cross-refs to health sections + snapshot ID |
| `feedback_to_governor.*.source_refs` | Bus snapshot + watchlist health at feedback time |

Full schema + JSON examples: `OUTCOME_BUS_IMPLEMENTATION.md` (Traceability sections).

## Daily Learning Scorecard (2026-07-05)

**CLI:** `python3 scripts/hermes_learning_scorecard.py --json`  
**Output:** `data/runtime/hermes_learning_scorecard.json`  
**API:** `GET /api/v2/hermes/learning-scorecard` (`?refresh=1` to regenerate)  
**UI:** Command Center → Hermes → Closed Loop → **Learning Scorecard** (top of panel)

Aggregates outcome bus, scope governor changes, research rows, operator accept/reject on threshold proposals,
FP/FN proxies, resource efficiency, learned vs static thresholds, and maturity-by-subsystem. **Advisory-only**
— no broker or execution writes.

## Evidence gates & do-no-harm (2026-07-05)

| Module | Role |
|--------|------|
| `lib/hermes_thresholds/evidence_gates.py` | `sample_size`, `confidence`, `allowed_action`; blocks “learned” without minimum sample |
| `lib/hermes_thresholds/counterfactual_evidence.py` | Top help/hurt examples + estimated FP/FN/coverage/resource impact per proposal |
| `lib/hermes_thresholds/do_no_harm.py` | Before/after regression after `--evaluate`; recommends **revert** when metrics degrade |
| `lib/hermes_thresholds/governance.py` | Hard advisory-only boundary — broker writes, OCO, stops, 2FA blocked |

**Eval CLI:** `python3 scripts/hermes_threshold_evaluator.py --json` (alias for learner `--evaluate` + do-no-harm artifact)

Config: `config/hermes_thresholds.yaml` → `evidence_gates` section.

## Symbol journey API (traceability)

**GET** `/api/v2/hermes/symbol-journey?symbol=XYZ`

Returns merged timeline from:

- `scope_governor_audit` — tier changes
- `hermes_watchlist_lifecycle_audit` — blocks, overrides
- `hermes_outcome_ledger` — graded outcomes
- `paper_trades` — recent positions
- `outcome_bus.by_symbol` + `lifecycle.*` snapshots

**UI:** `/v3/hermes` → Closed Loop — click any watchlist, holdings, or bus symbol row.
DetailDrawer renders `SymbolJourneyPanel`: current state metrics, health component bars,
governor feedback, and a vertical timeline (not raw JSON).

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

9. `hermes_outcome_feedback_agent.py --apply` — bus contains `lifecycle.*`, `watchlist_health`, `holdings_health`, `threshold_proposals`, `lineage.snapshot_id`
10. Governor dry-run with bus — `stop_quality_*` reactions in `bus_reactions` when divergence/R-left triggers fire
11. `hermes_threshold_learner.py --evaluate` — threshold evals + `closed_loop` promotion-gate verdict
12. `GET /api/v2/hermes/symbol-journey?symbol=SCHD` — `timeline` with governor + outcome events
13. Proposal history shows `impact_narrative` + `evaluation_outcome` after `--evaluate`
14. `stop_quality.trends.window_7d` populated when ≥2 bus history days
15. `pytest tests/test_bus_traceability.py tests/test_symbol_journey.py tests/test_proposal_impact.py tests/test_lifecycle_bus_slice.py -q`

### Prompt 6 — Maturity hardening

16. `python3 scripts/hermes_learning_scorecard.py --json` — scorecard written with `advisory_only: true`
17. `GET /api/v2/hermes/learning-scorecard` — same metrics as CLI (Command Center panel)
18. `hermes_threshold_learner.py --review` — proposals include `evidence_gates` + `counterfactual_evidence`
19. `hermes_threshold_evaluator.py --json` — evaluations include do-no-harm recommendation when windows ready
20. `pytest tests/test_hermes_maturity_hardening.py -q` — gates, counterfactuals, governance, scorecard

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