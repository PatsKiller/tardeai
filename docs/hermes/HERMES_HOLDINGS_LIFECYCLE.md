# Hermes Holdings Lifecycle

**Status:** Live (2026-07-03) · advisory only · no auto-sell · `review_mode: true`

## Purpose

Holdings (S0 pins) get a **per-position health score** (0–100) and **lifecycle stage** driven heavily by **stop quality** and outcome bus signals. Operators see degradation before it appears only in stop alerts or LLM health chips.

Does not place orders or change `scope_tier` — complements Scope Governor and Outcome Bus.

## Holdings health score (0–100)

### Components & weights

| Component | Weight | Signals |
|-----------|--------|---------|
| **Stop quality** | **30%** | Hot-tier `aligned_pct`, `trail_activation_rate`, `r_left_on_table_avg` from outcome bus; governor pause/demote |
| Outcome consistency | 22% | `by_symbol` gate, lift, hit/miss graded samples |
| Realized R | 15% | `avg_r` from outcome bus |
| Research actionability | 13% | `holdings_llm_health`, flagged tags |
| Position risk | 20% | `gain_pct`, drawdown from 52w high |

Config: `config/hermes_holdings_lifecycle.yaml`

### Confidence discount

| `graded_n` (bus) | Tier | Multiplier |
|------------------|------|------------|
| &lt; 2 | `sparse_data` | ×0.88 |
| 2–3 | `low_confidence` | ×0.80 |
| ≥ 4 | `full` | ×1.0 |

Stored fields: `health_score`, `health_score_raw`, `confidence_tier`, `graded_n`, `health_components`.

### Daily history

`hermes_holdings_lifecycle.json` → `history.SYM[]` (14d default): `{ at, health_score, stage }`.

Nightly outcome bus → `holdings_health.symbols.SYM.health_history`.

## Lifecycle stages & transition rules

| Stage | Typical health | Entry rules (conservative) |
|-------|----------------|----------------------------|
| **healthy** | ≥ 70 | Default when health ≥ `healthy_min` and no adverse bus gate |
| **watch** | 50–69 | Health in watch band **or** `outcome_gate = demote_pressure` **or** `governor_action = demote_pressure` |
| **trim_candidate** | &lt; 50 | Health &lt; `watch_min` **or** `pause_eligible` **or** `governor_action = pause` |
| **exited** | — | Symbol removed from `holdings.json` |

Manual override via `POST /api/v2/hermes/holdings-lifecycle/override` — logged to audit, does not auto-sell.

### Recommended actions (advisory)

| Stage | `recommended_action` | Monitoring |
|-------|---------------------|------------|
| healthy | `monitor` | standard research · normal stops |
| watch | `review_stops_and_research` | elevated · tight |
| trim_candidate | `operator_trim_review` | full · tight |
| exited | `none` | none |

## Traceability linkage

```
holdings.json position
        ↓
holdings_lifecycle tick (governor :07/:37)
        ↓
health_score + stage → hermes_holdings_lifecycle.json + audit
        ↓
research_scheduler T0-HOLD multiplier (1.0–1.45×)
        ↓
outcome_bus.holdings_health (nightly)
        ↓
by_symbol.SYM.lineage.holdings_health_ref
```

## Modules & persistence

| Path | Role |
|------|------|
| `scripts/lib/hermes_holdings_lifecycle/holdings_lifecycle.py` | Scoring + stages + audit |
| `data/runtime/hermes_holdings_lifecycle.json` | Snapshot + `history` per symbol |
| `data/runtime/hermes_holdings_lifecycle_audit.jsonl` | Tick, `stage_transition`, override |

Refreshed on each Scope Governor tick and `GET /api/v2/hermes/holdings-lifecycle`.

**Research scheduler:** `holdings_research_multiplier()` for `T0-HOLD` — standard 1.0×, elevated 1.25×, full 1.45×.

**Outcome bus:** `holdings_health` top-level section via `bus_traceability.py` (see `OUTCOME_BUS_IMPLEMENTATION.md`).

## API

**GET** `/api/v2/hermes/holdings-lifecycle` — `panel_rows`, `summary`, `holdings`, `history`

**POST** `/api/v2/hermes/holdings-lifecycle/override`

```json
{ "symbol": "SCHD", "stage": "watch", "reason": "operator: review after stop widening", "by": "operator_ui" }
```

## UI

`/v3/hermes` → Closed Loop → **Holdings lifecycle** — health, **stop component**, stage, recommended action, monitoring hints. Click row → symbol journey.

## Example scenarios

### Healthy → Watch

1. **SCHD** health 74, stop component 68 → stage **healthy**
2. Bus grades demote_pressure after weak promotion outcomes
3. Next tick: health 58 (outcome consistency ↓), stage **watch**, action `review_stops_and_research`
4. Research scheduler applies **1.25×** priority for T0-HOLD
5. Audit logs `stage_transition` with components snapshot

### Watch → Trim Candidate

1. **XYZ** health 52, stop component 41 (low trail + high R-left)
2. Bus gate → `pause_eligible`
3. Stage **trim_candidate**, action `operator_trim_review`, monitoring **full/tight**
4. Operator reviews in Closed Loop — no auto-sell

## Validation checklist

1. `hermes_scope_governor.py --dry-run` — stdout includes `holdings_lifecycle.summary`
2. `data/runtime/hermes_holdings_lifecycle.json` — `health_components.stop_quality`, `confidence_tier`, `history`
3. `GET /api/v2/hermes/holdings-lifecycle` — `panel_rows` with `recommended_action`
4. `research_scheduler.py --mode holdings --dry-run` — trim/watch symbols show elevated multiplier
5. `hermes_outcome_feedback_agent.py --apply` — `holdings_health.position_count` populated
6. Closed Loop — Holdings table shows Stop column + action hints
7. `POST .../holdings-lifecycle/override` — audit row + override in state
8. `pytest tests/test_holdings_lifecycle.py -q`

## Related

- `HERMES_SCOPE_GOVERNOR.md` — S0 pins, governor tick
- `HERMES_WATCHLIST_LIFECYCLE.md` — non-holding symbols
- `HERMES_CLOSED_LOOP_TRACEABILITY.md` — end-to-end validation
- `OUTCOME_BUS_IMPLEMENTATION.md` — `holdings_health` schema