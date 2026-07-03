# Hermes Watchlist Lifecycle

**Status:** Phase 2 (2026-07-03) · advisory · parallel to `scope_tier` (S0–S3)

## Purpose

The watchlist lifecycle adds an **operator-facing stage** and **conviction score** on top of the Scope Governor’s tier assignments. It does **not** replace `watchlist_items.scope_tier` — tier writes remain owned by `hermes_scope_governor.py --apply`.

Outcome yield drives conviction adjustments; promotion/demotion **recommendations** surface in the Closed Loop panel before tier changes are applied.

## Stages

| Stage | Meaning | Typical tier |
|-------|---------|--------------|
| **new** | Discovery grace (< 7d on watchlist) | S2 / S3 |
| **monitoring** | Warm/cold watch, neutral outcomes | S2 / S3 |
| **watch** | Health 45–59 or 7d decline ≥ 10 pts — elevated scrutiny | S2 / S3 |
| **promoted** | Hot attention — holdings, S0/S1, or pending promote | S0 / S1 |
| **demoted** | Outcome demotion pressure or pending demote | S2 / S3 |
| **archived** | Cold, low conviction, no fresh trigger | S3 |
| **blacklisted** | Manual override or outcome pause eligible | S3 |

## Conviction score (0–100)

Base = Scope Governor `edge_score`. Adjustments from:

- `outcome_gate`: promote_eligible (+8), demote_pressure (−18), pause_eligible (−28)
- Nightly `feedback_to_governor` bus actions (promote / demote / pause deltas)

Config: `config/hermes_watchlist_lifecycle.yaml`

## Health score (0–100) — Phase 2

Weighted composite from outcome bus + governor signals:

| Component | Weight | Source |
|-----------|--------|--------|
| outcome_performance | 0.25 | hit rate, avg R |
| promotion_success_rate | 0.15 | `hermes_outcome_ledger` promotion hits |
| tag_lift_consistency | 0.15 | bus lift / precision |
| stop_quality | 0.25 | global stop alignment (trail, aligned %) |
| regime_alignment | 0.10 | regime label + ATR |
| research_efficiency | 0.10 | research actioned rate |
| edge_blend | 0.10 | scope governor edge score |

**Confidence discount:** sparse (`graded_n < 3` ×0.85), low (`< 5` ×0.75), full otherwise.

**Display score** (panel sort): `0.70 × health + 0.30 × edge_score`.

**Promotion health gate** (`block_weak_outcome_promotions: true`): outcome-driven S1 claims require `health ≥ 62`, `graded_n ≥ 3`, and not `sparse_data`. Blocked symbols are logged to `hermes_watchlist_lifecycle_audit.jsonl`.

## Transition rules (conservative)

1. **Promoted** — S0/S1 tier, pending promote/reactivate, or strong promote_eligible on warm tier
2. **Demoted** — `demote_pressure` gate or pending demote decision
3. **Blacklisted** — manual override only (except auto on `pause_eligible` when enabled)
4. **Re-promote cooldown** — 7d after demotion (documented; enforced in Phase 2 tier writes)
5. **min_graded_samples: 3** — inherited graft-gate philosophy from scope governor

## Modules

| Path | Role |
|------|------|
| `scripts/lib/hermes_scope_governor/watchlist_lifecycle.py` | Stage resolution, conviction, persistence |
| `scripts/lib/hermes_scope_governor/watchlist_health.py` | Health components, promotion gate |
| `config/hermes_watchlist_lifecycle.yaml` | Stages, thresholds, panel limit |
| `data/runtime/hermes_watchlist_lifecycle.json` | Latest snapshot per governor tick |
| `data/runtime/hermes_watchlist_lifecycle_audit.jsonl` | Tick + manual override audit |

Wired into `ScopeGovernorEngine.run()` after each dry-run or `--apply` tick.

### Outcome bus export

Nightly `hermes_outcome_feedback_agent.py --apply` writes:

| Bus key | Contents |
|---------|----------|
| `lifecycle.watchlist` | Compact stage/health summary (backward compatible) |
| `watchlist_health` | Full scores, 6 `components`, `health_history`, `data_quality`, `lineage` |
| `by_symbol.SYM.watchlist_lifecycle` | Compact per-symbol slice |
| `by_symbol.SYM.lineage.watchlist_health_ref` | Cross-ref to `watchlist_health.symbols.SYM` |

Module: `scripts/lib/hermes_outcome_bus/bus_traceability.py` (see `OUTCOME_BUS_IMPLEMENTATION.md`).

## API

**GET** `/api/v2/hermes/scope-governor`

- `watchlist_lifecycle` — full snapshot (`panel_rows`, `pending_transitions`, `summary`)
- `watchlist_lifecycle_audit` — recent audit tail

**POST** `/api/v2/hermes/watchlist-lifecycle/override`

```json
{ "symbol": "TSLA", "stage": "blacklisted", "reason": "operator: noise symbol", "by": "operator_ui" }
```

Requires `reason` ≥ 3 characters. Does not change `scope_tier` — override affects lifecycle display until cleared.

## UI

`/v3/hermes` → Closed Loop → **Watchlist lifecycle** table:

- Symbol, stage, tier, **health** (7d trend arrow), conviction, outcome gate, pending transition or stage reason
- Amber border when a pending tier transition exists or stage is **watch**
- Subtitle when outcome promotions were blocked by health gate

## 9. Validation checklist

Run after deploy or config change:

1. **Dry-run governor** — `.venv/bin/python scripts/hermes_scope_governor.py --dry-run` completes with `watchlist_lifecycle.summary` in stdout JSON.
2. **Lifecycle file** — `data/runtime/hermes_watchlist_lifecycle.json` has `health_score`, `health_components`, `health_history` per symbol.
3. **Promotion gate** — symbols with `edge ≥ hot_min` but `health < 62` appear in `blocked_promotions` and audit `blocked_promotion` rows; they do **not** get `outcome_edge>=` in `want` claims.
4. **Watch stage** — symbol with health 45–59 (and not S0/S1) shows `lifecycle_stage: watch`; 7d drop ≥ 10 pts also triggers watch.
5. **API** — `GET /api/v2/hermes/scope-governor` returns `watchlist_lifecycle.panel_rows` with health fields.
6. **UI** — `/v3/hermes` → Closed Loop → Watchlist lifecycle shows Health column and trend arrows.
7. **Override** — `POST /api/v2/hermes/watchlist-lifecycle/override` still works; does not change `scope_tier`.
8. **Tests** — `.venv/bin/python -m pytest tests/test_watchlist_lifecycle.py -q` all pass.
9. **Phase D evaluation** — `.venv/bin/python scripts/hermes_threshold_learner.py --evaluate` includes `closed_loop` verdict for promotion gate; or `--closed-loop-evaluate` alone.

## 10. Example scenarios

### A — Strong edge, weak health (gate blocks promotion)

- Symbol `XYZ` on S2, `edge_score = 68`, `outcome_gate = promote_eligible`.
- Health: `outcome_performance = 38`, `graded_n = 4` → composite **54** (after discount).
- Governor **does not** add `outcome_edge>=65` S1 claim; audit logs `blocked_promotion` with `health=54<62`.
- Lifecycle stage: **watch** (health band 45–59).

### B — Proven promoter (passes gate)

- Symbol `ABC` on S2, `edge_score = 71`, `graded_n = 8`, health **67**, confidence **full**.
- Passes promotion gate → pending `S2→S1 promote`; lifecycle **promoted**.
- Panel sorts by `display_score` (~69).

### C — Declining health trend

- `health_history` shows 72 → 65 → 58 over 7d (`health_trend = -14`).
- Stage flips to **watch** even if current health is 58 (band) or 62 (trend rule fires first at ≤ −10).
- UI shows red ↓14 next to health.

### D — Manual blacklist during pause

- Operator POST override `blacklisted` with reason; stage overrides `pause_eligible` auto-blacklist path when override set.
- Tier unchanged until separate `--apply` demotion.

## 11. Phase D — closed-loop evaluation

After the promotion health gate has been active ≥7d (config: `evaluation.min_days_after_activation`):

| Command | Purpose |
|---------|---------|
| `--evaluate` | Threshold before/after **plus** watchlist gate evaluation |
| `--closed-loop-evaluate` | Gate-only evaluation (read-only) |

**Metrics compared:** `hit_rate_promotions` and `maturity_composite_score` in before/after windows around gate activation; counterfactual `blocked_symbol_promo_hit_rate` from `hermes_outcome_ledger`.

**Storage:** `data/runtime/hermes_closed_loop_evaluations.json` · audit `hermes_closed_loop_eval_audit.jsonl`

**API:** `GET /api/v2/hermes/closed-loop/evaluations` · `POST /api/v2/hermes/closed-loop/evaluate`

**UI:** Closed Loop → Watchlist lifecycle → **Promotion gate validation** card.

**Verdicts:** `helped` → `keep_gate` · `neutral` → `monitor` · `hurt` → `review_gate` · thin data → `needs_more_data`

## Related

- `HERMES_SCOPE_GOVERNOR.md` — tier owner
- `HERMES_THRESHOLD_EVALUATION_ENGINE.md` — threshold before/after engine
- `OUTCOME_BUS_IMPLEMENTATION.md` — `feedback_to_governor`
- `HERMES_ADAPTIVE_THRESHOLD_LEARNING.md` — bus reactions adjust promotion caps