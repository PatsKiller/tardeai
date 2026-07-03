# Hermes Scope Governor Agent

**Status:** production v2 (2026-07-02) · advisory-only · sole owner of `watchlist_items.scope_tier`

## Purpose

The Scope Governor is the **single source of truth** for what Hermes actively monitors. It replaces the legacy ~5,000-symbol flat sweep with a governed, outcome-aware, tiered universe.

| Heat | Scope tier | Monitoring cadence | Role |
|------|------------|-------------------|------|
| **Hot** | S0 + S1 | 15m / 30m market hours | Deep research + high-frequency scoring |
| **Warm** | S2 | Premarket daily | Incubator / watchpool / capped directives |
| **Cold** | S3 | Event-only | Archived — rescored only on catalyst/news/Finviz/proposal events |

**Design law:** outcome yield outranks throughput yield. A high composite score alone does not earn Hot tier if graded outcomes are poor.

## Architecture

```
Inputs (portfolio, outcomes, social, regime, events)
        ↓
  SymbolSignals + EdgeScore (weighted, graft-gated)
        ↓
  ScopeGovernorEngine (rules + caps + TTL demotions)
        ↓
  watchlist_items.scope_tier + scope_governor_audit
        ↓
  hermes_governed_universe.json (versioned feed for Hermes)
```

### Modules

| Path | Role |
|------|------|
| `scripts/hermes_scope_governor.py` | CLI entry (`--apply`, `--dry-run`, `--inspect`) |
| `scripts/lib/hermes_scope_governor/engine.py` | Decision engine |
| `scripts/lib/hermes_scope_governor/scoring.py` | Outcome-aware edge scoring |
| `scripts/lib/hermes_scope_governor/inputs.py` | Signal aggregation |
| `scripts/lib/hermes_scope_governor/universe.py` | Governed universe feed |
| `scripts/lib/hermes_scope_governor/watchlist_lifecycle.py` | Advisory lifecycle stages + conviction |
| `scripts/lib/hermes_scope_governor/watchlist_health.py` | Composite health score + promotion gate |
| `config/hermes_scope_governor.yaml` | Tunable rails + scoring weights |
| `config/hermes_watchlist_lifecycle.yaml` | Health weights, watch stage, promotion floor |

### Cron

- Governor: `:07,:37` (every 30 min) — `hermes_scope_governor.py --apply`
- Event feeder: `*/5` — `hermes_score_event_feeder.py --apply` (S3→S1 reactivation)
- Scorer: `*/15` tier-mode — consumes `scope_tier`

## Inputs

| Source | Signal |
|--------|--------|
| Portfolio holdings | S0 pin |
| Open momentum scalps (`state/momentum_scalp/open_scalps.json`) | S0 pin |
| Open paper positions / live proposals | S0 pin |
| Operator ticker directives | S0 pin |
| `hermes_outcome_ledger` | Hit/miss rate, avg realized R, actioned research |
| `intelligence_entities` | Social score, RVOL, liquidity, ATR |
| `market_regime_snapshots` | Regime tilt on scoring |
| `catalyst_events`, `watch_directive_hits`, `hermes_score_event_queue` | Event boosts |
| `watchlist_items` | Composite, rank, active status |
| Incubator / strategy watchpool | S2 membership |

## Decision rules

### Hard pins (S0 — never TTL-demoted)

- Holdings, open scalps, open positions, live proposals, operator ticker directives

### S1 triggers (Hot)

- Composite ≥ 70
- Fresh catalyst (< 48h)
- Active watchlist status
- Capped fresh directive hit
- **Outcome promotion:** edge score ≥ `hot_min_score` (default 65) with graft-gate `promote_eligible`, **and** watchlist health ≥ `promote_floor` (62) when `block_weak_outcome_promotions` is enabled (see `HERMES_WATCHLIST_LIFECYCLE.md`)

### S2 triggers (Warm)

- Active incubator / strategy watchpool (recency-gated)
- Directive top-N per directive (global cap 200)

### Demotions / pause

- TTL: S1 → S2 after 14d without fresh trigger; S2 → S3 after 30d
- **Outcome pause:** miss rate ≥ 75% with ≥ 4 graded samples → force S3 (unless S0)
- **Cap overflow:** shed lowest edge_score symbols first (S2 before S1, unclaimed before claimed)

### Graft gates (do not overreact)

- Minimum 3 graded outcomes before demotion/promotion gates apply
- Single wins cannot promote without `promote_hit_rate` threshold
- `max_outcome_promotions: 25` per run
- **Watchlist health gate (Phase 2):** outcome S1 claims blocked when health &lt; 62, `graded_n &lt; 3`, or `confidence_tier = sparse_data`; logged as `blocked_promotion` in `hermes_watchlist_lifecycle_audit.jsonl`

## Outputs

1. **Tier assignment** on every watchlist symbol (`scope_tier`)
2. **Audit log** — `scope_governor_audit` (run_id, action, from/to, reason + edge evidence)
3. **Governed universe feed** — `data/runtime/hermes_governed_universe.json`
4. **Watchlist lifecycle snapshot** — `data/runtime/hermes_watchlist_lifecycle.json` (stages, conviction, **health score**, 14d `health_history`, `blocked_promotions`; see `HERMES_WATCHLIST_LIFECYCLE.md`)
5. **Holdings lifecycle snapshot** — `data/runtime/hermes_holdings_lifecycle.json` (see `HERMES_HOLDINGS_LIFECYCLE.md`)
6. **API** — `GET /api/v2/hermes/scope-governor` (+ `watchlist_lifecycle`, override POST)

## Closed-loop feedback

| Good outcome | Governor response |
|--------------|-------------------|
| Hit rate ≥ 50%, avg R ≥ 0.25 | Edge boost + eligible for outcome S1 promotion |
| Actioned research | Higher outcome_yield component |

| Poor outcome | Governor response |
|--------------|-------------------|
| Miss rate ≥ 60% | Demotion pressure (−20 edge score) |
| Miss rate ≥ 75%, n ≥ 4 | Pause to S3 (unless capital-exposed S0) |
| Low liquidity / high ATR | Liquidity penalty |

Over time, symbols that consistently deliver low graded value drift to Cold (S3) and stop clock-driven scoring — compounding intelligence, not activity.

### Stop-quality bus reactions (`config/hermes_reactions.yaml`)

| Reaction id | Trigger | Effect |
|-------------|---------|--------|
| `stop_quality_divergence` | Hot vs cold trail delta below floor N days | Hot min bump, warm/cold edge penalty, research boost |
| `stop_quality_strong_advantage` | Trail delta ≥ strong advantage | Relax hot min, hot edge boost |
| `stop_quality_r_left_worsening` | R-left-on-table trend worsening / above ceiling | Hot min bump |
| `stop_quality_alignment_divergence` | Hot−cold aligned% below floor | Warm/cold edge penalty |
| `stop_quality_post_promotion_degradation` | Recent S0/S1 promotes with poor stop/outcome | Per-symbol edge penalty, demotion pressure |

All reactions log metric snapshots to `scope_governor_audit` (`__BUS__` rows) and optional `hermes_bus_reactions.json` runtime overrides.

## Conservative starting parameters

Already set in `config/hermes_scope_governor.yaml`:

- `total_cap: 800` (S0+S1+S2)
- `outcome_yield` weight 30% (highest)
- `min_graded_samples: 3`
- `hot_min_score: 65`
- `max_outcome_promotions: 25` per run
- `llm_ambiguous_review.enabled: false` (rules-first)

## Cron (observable — not silent skip)

Uses `safe_flock.sh` so every run is logged to `logs/safe_flock_events.jsonl` (started / lock_skip / completed):

```cron
7,37 * * * *  ... safe_flock.sh /tmp/hermes_scope_governor.lock ... hermes_scope_governor.py --apply
*/5 * * * *   ... safe_flock.sh /tmp/hermes_event_feeder.lock ... hermes_score_event_feeder.py --apply
```

Heartbeats (for health agent):

- `data/runtime/hermes_scope_governor_heartbeat.json`
- `data/runtime/hermes_event_feeder_heartbeat.json`

## Health monitoring

| Monitor | What it checks |
|---------|----------------|
| `health_agent.py` → `collect_hermes_scope_governor_health` | Heartbeat age, crontab present, safe_flock skips, audit runs/24h, universe feed freshness |
| `hermes_pipeline_health.py` | Same probes folded into nightly Hermes watchdog |

Surfaces in Command Center **System → Health** under `intelligence_quality` (types like `hermes_scope_governor_stale`, `hermes_event_feeder_stale`).

## Inspection

```bash
python3 scripts/hermes_scope_governor.py --inspect
python3 scripts/hermes_scope_governor.py --inspect --symbol SCHD
curl -s http://127.0.0.1:7777/api/v2/hermes/scope-governor | jq '.counts_by_heat'
tail -f logs/safe_flock_events.jsonl | rg hermes_scope
```

## Validation checklist

- [ ] `live_universe` ≤ `total_cap` (800)
- [ ] All holdings present in S0 every run
- [ ] Governor converges to 0 changes on quiet re-run
- [ ] `scope_governor_audit` rows for every tier change
- [ ] `hermes_governed_universe.json` updates on `--apply`
- [ ] Poor-outcome symbols demote; proven-edge symbols promote
- [ ] `estimated_score_computations_per_day` < 15K (vs ~197K pre-governor)
- [ ] Event feeder reactivates S3 names within minutes of catalyst
- [ ] Maturity gate `governor_active` ≥ 1 run/24h
- [ ] `GET /api/v2/hermes/scope-governor` returns heat counts + recent audit
- [ ] Weak-health symbols with high edge appear in `watchlist_lifecycle.blocked_promotions`, not in `want` outcome claims
- [ ] Closed Loop panel shows watchlist health column + 7d trend (see `HERMES_WATCHLIST_LIFECYCLE.md` §9)

## Tests

```bash
python3 -m unittest tests.test_hermes_scope_governor -v
python3 -m unittest tests.test_watchlist_lifecycle -v
```