# Hermes Holdings Lifecycle

**Status:** Phase 1 (2026-07-03) · advisory only · no auto-sell

## Purpose

Holdings (S0 pins) get a **per-position health score** (0–100) and **lifecycle stage** so operators can see degradation before it shows up only in stop alerts or LLM health chips.

Does not place orders or change `scope_tier` — complements Scope Governor and Outcome Bus.

## Stages

| Stage | Health (typical) | Meaning |
|-------|------------------|---------|
| **healthy** | ≥ 70 | Normal monitoring |
| **watch** | 50–69 or demote pressure | Early degradation — elevated research + tighter stop watch |
| **trim_candidate** | &lt; 50 or pause eligible | Review for trim/exit (operator decision only) |
| **exited** | — | No longer in `holdings.json` |

## Health score components

| Component | Weight | Signals |
|-----------|--------|---------|
| Stop quality | 25% | Bus `stop_quality`, governor pause/demote on holding |
| Outcome consistency | 25% | `by_symbol` gate, lift, hit/miss graded samples |
| Realized R | 15% | `avg_r` from outcome bus |
| Research actionability | 15% | `holdings_llm_health`, flagged tags |
| Position risk | 20% | `gain_pct`, drawdown from 52w high (`technical_snapshot`) |

Config: `config/hermes_holdings_lifecycle.yaml`

## Monitoring hints (advisory)

| Stage | Research depth | Stop monitoring |
|-------|----------------|-----------------|
| healthy | standard | normal |
| watch | elevated | tight |
| trim_candidate | full | tight |

## Modules & persistence

| Path | Role |
|------|------|
| `scripts/lib/hermes_holdings_lifecycle/holdings_lifecycle.py` | Scoring + stages |
| `data/runtime/hermes_holdings_lifecycle.json` | Latest snapshot + health history per symbol |
| `data/runtime/hermes_holdings_lifecycle_audit.jsonl` | Tick + override audit |

Refreshed on each Scope Governor tick (`:07/:37`) and on `GET /api/v2/hermes/holdings-lifecycle`.

## API

**GET** `/api/v2/hermes/holdings-lifecycle` — `panel_rows`, `summary`, `holdings`, per-symbol `history`

**POST** `/api/v2/hermes/holdings-lifecycle/override`

```json
{ "symbol": "AAPL", "stage": "watch", "reason": "operator: review after earnings gap", "by": "operator_ui" }
```

## UI

`/v3/hermes` → Closed Loop → **Holdings lifecycle** table (health, stage, gain %, monitoring hints).

## Related

- `HERMES_SCOPE_GOVERNOR.md` — S0 pins
- `HERMES_WATCHLIST_LIFECYCLE.md` — non-holding watchlist symbols
- `OUTCOME_BUS_IMPLEMENTATION.md` — `by_symbol`, `feedback_to_governor`