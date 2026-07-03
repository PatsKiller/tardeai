# Outcome Bus — Implementation Guide

**Status:** Production · `outcome-bus-v1` · 2026-07-02

This document describes the **real** closed-loop implementation. Any SQLite-based example code (e.g. from early design drafts) is **obsolete** — do not copy it.

---

## What it does

The Outcome & Feedback Agent rolls up graded trade outcomes into `state/hermes/outcome_bus.json`. The Scope Governor and Research Agent read that file nightly — no message queue, no MARL.

**Design law:** outcome yield outranks throughput yield.

---

## Nightly cadence

| Time (UTC) | Job | Output |
|------------|-----|--------|
| `02:50` | `hermes_outcome_grader.py` | Grades `hermes_outcome_ledger` |
| `03:05` | `hermes_tag_engine.py` | Refreshes `hermes_tag_efficacy` |
| `03:25` | `hermes_outcome_feedback_agent.py` | Writes `outcome_bus.json` |
| `03:35` | `hermes_outcome_learning.py` | Weight/source/lane learning |

Tag engine runs **before** feedback so `by_tag` uses fresh lift/precision.

---

## Source files

| File | Role |
|------|------|
| `scripts/hermes_outcome_feedback_agent.py` | Bus builder (rules-only, zero LLM) |
| `config/hermes_outcome_feedback.yaml` | Thresholds, S3 policy metadata |
| `scripts/lib/hermes_outcome_bus/bus.py` | Atomic read/write + history snapshots |
| `scripts/lib/hermes_scope_governor/outcome_bus.py` | Governor consumes `feedback_to_governor` |
| `scripts/research_scheduler.py` | Research priority × `quality_multiplier` |
| `scripts/hermes_score_event_feeder.py` | Multi-factor S3 reactivation |
| `state/hermes/outcome_bus.json` | Live bus |
| `state/hermes/outcome_bus_history/` | Versioned snapshots |
| `data/runtime/hermes_outcome_feedback_heartbeat.json` | Last run summary |

---

## Data sources (PostgreSQL)

| Bus section | Tables / feeds |
|-------------|----------------|
| `global.hit_rate_promotions` | `hermes_outcome_ledger` — `promotion`, `external_rec` verdicts |
| `global.hit_rate_research_actioned` | `hermes_outcome_ledger` — `research_row` action hits |
| `global.hit_rate_trades` | `hermes_outcome_ledger` — `trade` hit/miss + realized R |
| `by_symbol` | Price-graded ledger per symbol + dominant tag from `hermes_research_intelligence` |
| `by_tag` | `hermes_tag_efficacy` (`lift`, `precision`, `trade_n`) |
| `stop_quality` | `protection_advisory_outcomes` + `trade_mfe_analysis` (trail, alignment, MAE exceeded) |
| `resource_efficiency` | `hermes_score_history`, `hermes_external_research`, governed universe feed, `hermes_api_requests.jsonl` |

### `resource_efficiency` (v1.0 canonical)

```json
{
  "score": 0.78,
  "components": {
    "hit_rate_promotions": 0.372,
    "research_rows_per_positive_outcome": 18.4,
    "universe_stability": 0.91
  },
  "trend_7d": "improving",
  "calculation_version": "v1.0",
  "resource_efficiency_score": 0.78,
  "score_components": { },
  "positive_outcomes_7d": 25,
  "research_rows_per_positive_outcome": 51.9,
  "llm_calls_per_positive_outcome": 2.0,
  "hermes_api_calls_7d": 412,
  "live_universe_vs_baseline_pct": 0.12,
  "write_reduction_vs_baseline_pct": 0.55
}
```

**Score formula (v1.0):** 40% promotion hit rate (capped at 0.6) + 40% research efficiency `max(0, 1 - rows_per_outcome/50)` + 20% universe stability `1 - abs(universe_change_pct_7d)`. Uses real `positive_outcomes_7d` from ledger (not estimated). `trend_7d` compares current score to earliest point in 7d bus history. Legacy alias: `resource_efficiency_score` = `score`.

**Request log:** `state/hermes/hermes_api_requests.jsonl` — appended by `portfolio_server.py` on every `/api/v2/hermes/*` GET. Fields: `ts`, `endpoint`, `method`, `latency_ms`, `status`.

### `stop_quality` (v1.1)

```json
{
  "sample_n": 42,
  "aligned_pct": 0.65,
  "trail_activation_rate": 0.42,
  "r_left_on_table_avg": 0.18,
  "mae_exceeded_planned_stop_pct": 0.12,
  "by_tier": {
    "hot": { "sample_n": 15, "trail_activation_rate": 0.55, "aligned_pct": 0.70 },
    "warm": { "sample_n": 8, "trail_activation_rate": 0.45 },
    "cold": { "sample_n": 19, "trail_activation_rate": 0.37 }
  },
  "correlations": [
    {
      "metric": "trail_activation_rate",
      "hot_vs_cold_delta_pct": 18,
      "hot_vs_cold_trail_activation_delta": 0.18,
      "note": "Hot tier symbols have 18% higher trail activation rate vs Cold"
    }
  ]
}
```

Tier breakdown uses **current** governed-universe scope at analysis time (v1 pragmatic). All fields optional — missing tables yield `notes: insufficient_sample` or `table_unavailable`.

---

## Consumer schema (stable contract)

### `by_symbol`

```json
{
  "outcome_hits": 2,
  "misses": 1,
  "n": 5,
  "avg_r": 0.31,
  "gate": "promote_eligible",
  "edge_boost": 8,
  "edge_penalty": null,
  "dominant_tag": "momentum_scalp",
  "lift": 0.042,
  "precision": 0.61,
  "last_graded": "2026-07-02"
}
```

`gate` values: `promote_eligible`, `demote_pressure`, `pause_eligible`, `promote_blocked_bad_tag`, `neutral`.

### `by_tag`

```json
{
  "lift": 0.042,
  "precision": 0.553,
  "trade_n": 872,
  "quality_multiplier": 1.15,
  "n": 872,
  "flagged": false
}
```

### `feedback_to_governor`

```json
{
  "symbol": "XYZ",
  "action": "demote_pressure",
  "reason": "miss_rate>=60%,n=5",
  "edge_penalty": -20,
  "priority": 2,
  "evidence": { }
}
```

### Behavior rules (enforced)

1. **Split hit rates** in `global` — never one blended number.
2. **Tag demotion** requires negative tag lift **and** poor symbol outcomes (`n ≥ 3`).
3. **Promotion blocked** when dominant tag `lift < 0` or flagged.
4. **S3 reactivation** requires ≥2 factors (see `config/hermes_outcome_feedback.yaml`).

---

## Alerts & maturity (v1.2)

Nightly trend evaluation adds `alerts` and `maturity` sections to `outcome_bus.json`.

### `alerts` (v1.4 — actionable drilldown)

```json
{
  "active": [
    {
      "id": "hit_rate_declining",
      "label": "Hit rate declining",
      "severity": "warning",
      "since": "2026-07-01",
      "duration_days": 7,
      "detail": "hit_rate_promotions fell 9.0% over 7d (0.45 → 0.36)",
      "metrics": { "baseline": 0.45, "current": 0.36, "delta_pp": -0.09, "window_days": 7 },
      "contributors": {
        "symbols": [
          { "symbol": "BAD", "hits": 0, "misses": 5, "n": 5, "hit_rate": 0.0, "gate": "pause_eligible", "lift": -0.2 }
        ],
        "tags": [
          { "tag": "general_research", "lift": -0.29, "n": 500 }
        ]
      },
      "drilldown": {
        "summary": "5 worst-performing symbols; 2 tags with negative lift...",
        "root_causes": ["Price-graded outcomes declining vs 7d baseline"],
        "panel_path": "/v3/hermes",
        "governor_audit_endpoint": "/api/v2/hermes/scope-governor",
        "symbol_links": { "BAD": [{ "label": "Outcome bus", "endpoint": "/api/v2/hermes/outcome-bus?symbol=BAD" }] }
      }
    }
  ],
  "active_count": 1,
  "evaluated_at": "2026-07-03T03:25:00+00:00",
  "history_window_days": 14,
  "trend_points": 12,
  "enabled": true
}
```

Enrichment: `scripts/lib/hermes_outcome_bus/alert_enrichment.py` (nightly, before bus write).

### Alert notifications (`config/hermes_alerts.yaml`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `notifications.enabled` | `true` | Master switch |
| `cooldown_hours` | `8` | Per alert-id Telegram cooldown |
| `min_severity` | `warning` | Skip `info`-level |
| `alert_types.*` | per-type | Enable/disable notification per alert id |
| `channels.telegram.bypass_router` | `true` | Closed-loop alerts bypass generic Hermes suppression |

Dispatch: `scripts/lib/hermes_outcome_bus/alert_notifications.py` — called on `--apply` when alerts active.

Audit log: `state/hermes/alert_notification_audit.jsonl`  
Cooldown state: `data/runtime/hermes_alert_notification_state.json`

| Alert ID | Condition (defaults) |
|----------|---------------------|
| `hit_rate_declining` | `hit_rate_promotions` dropped ≥ **8pp** over **7d** |
| `efficiency_declining` | `resource_efficiency.score` < **0.55** for **3+** consecutive days |
| `scope_creep` | `symbols_in_bus` grew > **15%** over **14d** while hit rate flat (±2pp) or declined |
| `stop_quality_divergence` | Hot vs Cold `trail_activation_rate` delta < **15pp** for **5+** consecutive days |

Thresholds: `config/hermes_outcome_feedback.yaml` → `alerts:`.

### `maturity` (v2 composite 0–100)

Computed by `scripts/lib/hermes_outcome_bus/maturity.py` from `config/hermes_maturity.yaml`.

| Component | Weight | Signals |
|-----------|--------|---------|
| outcome_yield | 30% | promotion hit rate, trade hit rate, graded sample depth |
| scope_discipline | 25% | resource efficiency, universe vs baseline, scope growth |
| stop_quality | 20% | hot vs cold trail delta, alignment %, sample n |
| feedback_loop | 15% | governor/research feedback wired, active alert penalty |
| research_actionability | 10% | research action hit rate, positive-lift tag ratio |

**Tiers** (composite score): `nascent` 0–39 · `developing` 40–59 · `mature` 60–79 · `optimized` 80–100 (requires all components ≥ 55).

Daily snapshot: `state/hermes/hermes_maturity.json` (current + 30d `history[]`).

```json
{
  "version": "maturity-v2",
  "composite_score": 72,
  "tier": "mature",
  "overall_status": "mature",
  "trend": "improving",
  "components": {
    "outcome_yield": { "score": 68, "weight": 0.30, "trend": "stable", "signals": {} },
    "scope_discipline": { "score": 75, "weight": 0.25, "trend": "stable", "signals": {} },
    "stop_quality": { "score": 70, "weight": 0.20, "trend": "stable", "signals": {} },
    "feedback_loop": { "score": 80, "weight": 0.15, "trend": "stable", "signals": {} },
    "research_actionability": { "score": 65, "weight": 0.10, "trend": "stable", "signals": {} }
  },
  "maturity_score": 3.6,
  "design_ref": "config/hermes_maturity.yaml"
}
```

`maturity_score` = `composite_score / 20` for legacy chart compat. History trend points store `maturity_composite_score`, per-component scores, and `maturity_tier`.

---

## Scope Governor bus reactions (v2)

`scripts/lib/hermes_scope_governor/reactions.py` loads **`config/hermes_reactions.yaml`** (merges legacy `hermes_scope_governor.yaml` → `bus_reactions` for backward compat).

| Signal | Reaction |
|--------|----------|
| Efficiency `< tighten_threshold` for N days | `hot_min_score` bump; demotion pressure multiplier |
| Hot vs Cold trail delta below floor for N days | `hot_min_score` bump; S2/S3 edge penalty; hot research boost |
| Hot vs Cold trail delta ≥ strong advantage | `hot_min_score` relax; high-edge hot boost |
| Tag negative lift + poor outcomes N days | Temporary `quality_multiplier` reduction |
| `scope_creep` alert active | `max_outcome_promotions` reduction |

### Reaction configuration (`config/hermes_reactions.yaml`)

| Section | Key settings |
|---------|----------------|
| `review_mode` | `true` = log reactions, skip edge/cap/runtime apply |
| `cooldown` | `hours_per_reaction`, hysteresis release thresholds |
| `regime_modifiers` | Scale bumps under `high_volatility` vs `normal` |
| `efficiency` | `tighten_threshold`, `consecutive_days`, `hot_min_score_bump` |
| `stop_quality` | `divergence_delta_pp`, `divergence_consecutive_days`, penalties/boosts |
| `scope_creep` | `promotion_cap_reduction` |
| `tags` | `poor_outcomes_days`, `multiplier_reduction`, `multiplier_floor` |

**Review mode CLI:** `hermes_scope_governor.py --dry-run --reaction-review` (or `--apply --reaction-review` for audit rows prefixed `bus_reaction_review:`).

Each reaction includes `metrics` (bus snapshot at decision time), `regime`, and `review_mode`.

Cooldown state: `data/runtime/hermes_reaction_cooldown_state.json`  
Runtime overrides: `data/runtime/hermes_bus_reactions.json` (skipped in review mode)

---

## Closed Loop panel (alerts + maturity trend)

`/v3/hermes` → **Closed Loop** (`HermesClosedLoopPanel.tsx`):

- **Alerts banner** — prominent when `alerts.active_count > 0`
- **Maturity v2 card** — composite 0–100, tier badge, 5-component breakdown with weights/trends
- **Maturity trend chart** — 7d/30d composite from `maturity_trend.series`
- **Governor reactions** — active reactions with reasons + bus metrics; REVIEW MODE badge when applicable
- **Adaptive thresholds** — collapsible section (after Maturity, before Reactions):
  - Active vs static values with status badges (static / learned / pending review)
  - `pending_summary` line (e.g. `2 proposals pending review (Efficiency +0.03, Stop Quality Divergence -2pp)`)
  - Collecting-data state when `history_days < min_history_days` (non-alarming; learning activates at 14 bus days)
  - Inline proposal cards: confidence tier, reasoning, expected impact, top metric contributions
  - **Approve / Reject** — inline buttons open `ThresholdProposalModal` (see below); success/error toasts; list refresh on success
  - REST: `POST /api/v2/hermes/thresholds/proposals/{id}/approve|reject` (legacy `POST .../thresholds/approve|reject` still supported)
  - UI sends `force_apply: true` on approve so operator intent applies despite global `review_mode` (learner auto-apply remains blocked)
  - **Review in CLI** — copyable commands from `cli_commands` in API response
  - **Recent threshold audit** — last 8 approve/reject/propose events from `recent_audit`
  - **Holdout + counterfactual** — proposal cards show “would fire N×/14d”; modal shows key trigger days

---

## API

`GET /api/v2/hermes/outcome-bus` — includes `active_alerts`, `maturity`  
`GET /api/v2/hermes/outcome-bus?symbol=SCHD`  
`GET /api/v2/hermes/outcome-bus/history?days=7|30` — includes trend series, alert history, maturity  
`GET /api/v2/hermes/thresholds` — status, `pending_summary`, `history_days`, `learning_ready`, `recent_audit`, `cli_commands`  
`GET /api/v2/hermes/thresholds/evaluations` — post-approval impact evaluations  
`POST /api/v2/hermes/thresholds/proposals/{proposal_id}/approve` — body: `{ notes?, reason?, force_apply?: true }`  
`POST /api/v2/hermes/thresholds/proposals/{proposal_id}/reject` — body: `{ reason?, notes? }`  
`POST /api/v2/hermes/thresholds/approve` · `reject` (legacy) · `learn` · `evaluate`

Approve/reject audit rows append to `data/runtime/hermes_threshold_audit.jsonl` with proposal snapshot, operator, and `applied` flag.

### Threshold proposal confirmation modal

Component: `apps/command-center-v3/src/components/ThresholdProposalModal.tsx`

| Action | Modal title | Required input | Special UX |
|--------|-------------|----------------|------------|
| Approve | Approve Threshold Change | Notes optional (pre-filled from learner `reasoning`) | Loosening shows amber risk banner; evidence block shows confidence, top metrics, expected impact |
| Reject | Reject Threshold Proposal | Reason required (≥3 chars) | Reject disabled until reason entered |

Behavior: `Esc` closes · `Ctrl+Enter` confirms when valid · loading spinner text during API call · inline error (modal stays open) · green/red toast on success/failure · `GET /api/v2/hermes/thresholds` refetch after success.

Proposal evidence (scoring-v2 + Phase 3): `counterfactual` (fires in last 14d), `key_trigger_days`, `holdout_validation`, `metric_contributions`. Panel shows **Recent threshold audit** from `recent_audit` (last 8 rows of `hermes_threshold_audit.jsonl`).

---

## Commands

```bash
# Dry-run
.venv/bin/python scripts/hermes_outcome_feedback_agent.py

# Write bus + maturity snapshot
.venv/bin/python scripts/hermes_outcome_feedback_agent.py --apply

# Governor reaction review (log only, no runtime overrides)
.venv/bin/python scripts/hermes_scope_governor.py --dry-run --reaction-review

# Inspect maturity
cat state/hermes/hermes_maturity.json | jq '.composite_score, .tier, .components'

# Tests
.venv/bin/python -m unittest discover -s tests -p 'test_hermes_outcome_feedback.py'
```

## Post-nightly validation checklist

1. `outcome_bus.maturity.version` = `maturity-v2` and `composite_score` 0–100 present
2. `state/hermes/hermes_maturity.json` updated with today's `history[]` point
3. `GET /api/v2/hermes/outcome-bus/history?days=30` → `maturity_trend.series[].composite_score` populated
4. Governor dry-run shows `bus_reactions` with `metrics` when signals fire
5. `--reaction-review` sets `bus_reaction_review_mode: true` and skips `hermes_bus_reactions.json` write
6. Cooldown suppresses repeat reaction ids within `cooldown.hours_per_reaction`
7. High-vol regime scales `hot_min_score_bump` per `regime_modifiers.high_volatility`

---

## Obsolete example (do not use)

Early drafts showed `sqlite3` + `hermes_outcome_ledger.db` + hardcoded placeholders. The production stack uses **PostgreSQL** via `db_adapter`, real SQL, `--apply`, kill switch, and `safe_flock` cron locks.

---

## Adaptive threshold learning (Phase 1)

Governor reaction thresholds can be **learned** from outcome bus history with human approval:

- Config: `config/hermes_thresholds.yaml`
- Learner: `scripts/hermes_threshold_learner.py`
- Active values: `data/runtime/hermes_thresholds.json`
- Merged into `load_reactions_config()` at governor runtime

See `docs/hermes/HERMES_ADAPTIVE_THRESHOLD_LEARNING.md` for full design, CLI workflow, and validation checklist.

---

## Related docs

- `docs/hermes/HERMES_ADAPTIVE_THRESHOLD_LEARNING.md` — adaptive threshold learning
- `docs/hermes/HERMES_MULTI_AGENT_COORDINATION_ARCHITECTURE.md` — full multi-agent design
- `docs/hermes/HERMES_SCOPE_GOVERNOR.md` — tier logic
- `docs/design/HERMES_MATURITY_5_DESIGN.md` — maturity gates