# Hermes Threshold Evaluation Engine (Phase 2)
**Design Spec v1.0**  
**Date:** 2026-07-03  
**Status:** Implemented (Phase 2)

## 1. Objective

After Phase 1 enables **proposing and approving** threshold changes, Phase 2 answers: *did those changes actually help?*

The Evaluation Engine periodically compares key outcome metrics **before vs after** each approved threshold adjustment, producing conservative, evidence-based recommendations to keep, revert, or further tune.

## 2. Design Principles

| Principle | Requirement |
|-----------|-------------|
| Before/after only | No complex ML — paired window comparison |
| Conservative verdicts | "Uncertain" is a valid outcome when sample is thin |
| Linked to audit trail | Every evaluation references `proposal_id` + approval timestamp |
| Actionable output | Clear keep / revert / re-tune recommendations |
| Non-blocking | Evaluations inform humans; never auto-revert in v1 |

## 3. When to Run

| Cadence | Use case |
|---------|----------|
| **14 days** after approval | Minimum observation window (efficiency reactions) |
| **30 days** after approval | Preferred window for stop-quality thresholds |
| **Scheduled** | Weekly cron: `hermes_threshold_learner.py --evaluate` |
| **On-demand** | Operator or API trigger after major regime shift |

Config (`hermes_thresholds.yaml` → `evaluation`):

```yaml
evaluation:
  enabled: true
  min_days_after_change: 14
  preferred_days_after_change: 30
  before_window_days: 14        # same length as after window
  after_window_days: 14
  cadence_days: 7               # re-check pending evaluations weekly
```

## 4. Data Model

### `data/runtime/hermes_threshold_evaluations.json`

```json
{
  "version": "evaluations-v1",
  "updated_at": "2026-07-17T03:00:00+00:00",
  "evaluations": [
    {
      "id": "te_abc123",
      "threshold_id": "efficiency.tighten_threshold",
      "proposal_id": "tp_xyz",
      "approved_at": "2026-07-03T12:00:00+00:00",
      "evaluated_at": "2026-07-17T03:00:00+00:00",
      "change": { "from": 0.50, "to": 0.47 },
      "windows": {
        "before": { "start": "2026-06-19", "end": "2026-07-02", "days": 14 },
        "after":  { "start": "2026-07-04", "end": "2026-07-17", "days": 14 }
      },
      "metrics": {
        "hit_rate_promotions": { "before": 0.38, "after": 0.41, "delta": 0.03 },
        "avg_realized_r_trades_90d": { "before": 0.12, "after": 0.15, "delta": 0.03 },
        "resource_efficiency_score": { "before": 0.62, "after": 0.65, "delta": 0.03 },
        "maturity_composite_score": { "before": 68, "after": 72, "delta": 4 },
        "stop_hot_cold_trail_delta": { "before": 0.14, "after": 0.15, "delta": 0.01 }
      },
      "verdict": "helped",
      "confidence": "medium",
      "recommendation": "keep",
      "reasoning": "Promotion hit rate +3pp and maturity +4 after tightening; no efficiency regression.",
      "reaction_proxy": {
        "estimated_extra_reaction_days": 2,
        "false_positive_rate_delta": -0.05
      }
    }
  ]
}
```

### Append-only audit

`data/runtime/hermes_threshold_eval_audit.jsonl` — one row per evaluation run.

## 5. Metrics to Track (Success Definition)

Per threshold type, weighted composite **impact score** (−1 to +1):

### Efficiency threshold (`efficiency.tighten_threshold`)

| Metric | Weight | Better when |
|--------|--------|-------------|
| `hit_rate_promotions` (after) | 35% | Higher |
| `maturity_composite_score` | 25% | Higher |
| `avg_realized_r_trades_90d` | 20% | Higher |
| `resource_efficiency_score` | 10% | Stable or higher |
| Reaction precision proxy | 10% | Fewer false-positive reaction days |

### Stop quality divergence (`stop_quality.divergence_delta_pp`)

| Metric | Weight | Better when |
|--------|--------|-------------|
| `aligned_pct` | 30% | Higher |
| `maturity_stop_quality_score` | 25% | Higher |
| `stop_hot_cold_trail_delta` | 20% | Higher (Hot advantage preserved) |
| `hit_rate_promotions` | 15% | Not degraded |
| Governor reaction count | 10% | Not excessive |

### Verdict rules (conservative)

| Impact score | Verdict | Recommendation |
|--------------|---------|----------------|
| ≥ +0.15 | `helped` | `keep` |
| −0.05 to +0.15 | `neutral` | `monitor` |
| ≤ −0.15 | `hurt` | `revert` (human approval still required) |
| Sample < 10 days in either window | — | `insufficient_data` → `monitor` |

## 6. Architecture

```
hermes_thresholds.json (history[])
        ↓
evaluation_engine.py
  ├── load approval events from history + audit
  ├── for each change older than min_days_after_change:
  │     ├── slice outcome_bus_trend before/after windows
  │     ├── compute metric deltas
  │     ├── score impact + confidence
  │     └── write evaluation record
        ↓
hermes_threshold_evaluations.json
        ↓
CLI --evaluate / API GET /api/v2/hermes/thresholds/evaluations
        ↓
Closed Loop panel "Threshold impact" section (Phase 3)
```

### Module layout (proposed)

| File | Role |
|------|------|
| `scripts/lib/hermes_thresholds/evaluation_engine.py` | Core before/after analysis |
| `scripts/lib/hermes_thresholds/evaluation_store.py` | Read/write evaluations JSON |
| `scripts/hermes_threshold_learner.py` | Add `--evaluate` flag |

## 7. Confidence Indicators

Keep explainable — no p-values required in v1:

| Factor | Effect on confidence |
|--------|---------------------|
| ≥14 days in both windows | `medium` → `high` |
| <10 days in either window | `low` |
| Regime label changed between windows | downgrade one level |
| ≥2 metrics moved in same direction | upgrade one level |
| Active alerts increased after change | downgrade + flag in reasoning |

## 8. Implementation Approach (Lightweight)

### Step 1 — `evaluate_change(change_record)`

1. Parse `approved_at` from `hermes_thresholds.json` history entry
2. Load `outcome_bus_trend` for 60d
3. Split series into `before` (N days ending day before approval) and `after` (N days starting day after approval)
4. Average each metric per window
5. Compute weighted impact score
6. Emit verdict + recommendation

### Step 2 — `run_evaluation_cycle()`

- Iterate all `history` entries with `action == "approved"` not yet evaluated
- Skip if `days_since_approval < min_days_after_change`
- Append to evaluations file; log audit row

### Step 3 — Revert recommendation workflow

- `--evaluate` produces `recommendation: revert` entries
- Operator runs `--rollback` or targeted revert (Phase 2b)
- Never auto-revert in v1

## 9. API (Proposed)

```
GET  /api/v2/hermes/thresholds/evaluations
POST /api/v2/hermes/thresholds/evaluate   # trigger on-demand cycle
```

## 10. CLI

```bash
.venv/bin/python scripts/hermes_threshold_learner.py --evaluate
.venv/bin/python scripts/hermes_threshold_learner.py --evaluate --evaluation-id te_abc123
```

## 11. Phase 2 Deliverables Checklist

- [x] `evaluation_engine.py` + store
- [x] `evaluation` section in `hermes_thresholds.yaml`
- [x] `--evaluate` CLI + audit log
- [x] API endpoints (`GET /thresholds/evaluations`, `POST /thresholds/evaluate`)
- [x] Panel section: evaluation summary in Closed Loop → Adaptive thresholds
- [x] Tests: synthetic before/after series → expected verdict

## 12. Phase D — closed-loop evaluation (watchlist gate)

`--evaluate` now also runs `closed_loop_evaluation.py`:

- **Subject:** `watchlist_promotion_health_gate`
- **Windows:** before/after gate activation (first `blocked_promotion` audit row)
- **Counterfactual:** promotion hit rate for blocked symbols vs system `hit_rate_promotions` delta
- **CLI:** `--closed-loop-evaluate` (gate only) · included in `--evaluate`
- **API:** `GET/POST /api/v2/hermes/closed-loop/evaluations|evaluate`
- **Store:** `hermes_closed_loop_evaluations.json`

See `HERMES_WATCHLIST_LIFECYCLE.md` §11.

## 13. Future (post-approval evaluation)

- Regime-stratified evaluations (high-vol vs normal windows)
- Auto-suggest revert proposals when `hurt` + `high` confidence
- Holdings health trend evaluation (Phase D+)

**Note:** Proposal-time counterfactual (`evidence.counterfactual` — fires in last 14d) is implemented in the **Threshold Learner** (scoring Phase 3), not the evaluation engine. Evaluation engine remains read-only post-approval impact analysis.

---

**Related:** `HERMES_ADAPTIVE_THRESHOLD_LEARNING.md` · `HERMES_THRESHOLD_SCORING_REVIEW.md`