# Threshold Learner Scoring Logic — Review & Recommendations
**Date:** 2026-07-03  
**Reviewer:** Systems / quantitative engineering review (Phase 1)

## Executive Summary

The current learner is **sound for a conservative v1**: it is explainable, bounded, and cheap to run. Its main weakness is **over-reliance on a single proxy metric per threshold** (promotion hit rate for efficiency; alignment for stop quality) with a simplistic false-positive penalty. The recommendations below increase signal quality without adding ML complexity.

---

## 1. Scoring Fairness

### Current approach

```
score(T) = separation × (1 - trigger_rate_penalty)
```

where `separation` = baseline metric − conditional metric when threshold would fire.

### Strengths

- Easy to explain to operators
- Naturally penalizes thresholds that cry wolf too often
- Aligns with conservative governance (prefer fewer, higher-precision reactions)

### Weaknesses

- **Penalizing "fires too often" is necessary but not sufficient.** A threshold that fires rarely but never precedes degradation scores poorly even if it is safe.
- No reward for **early detection** — catching a 5pp hit-rate drop 3 days before a maturity decline is valuable but invisible today.
- Symmetric treatment of tighten vs loosen — loosening should require stronger evidence.

### Recommendations

1. **Add an early-detection term** (weight ~20%):

   ```
   lead_score = avg(hit_rate[t+1:t+3] - hit_rate[t]) when triggered at t
   ```

   Reward thresholds where trigger days precede measurable yield decline.

2. **Asymmetric evidence bar for loosening:**

   - Tighten proposals: current separation threshold (≥ 0.002 score improvement)
   - Loosen proposals: require 2× separation **and** trigger_rate < 25%

3. **Keep the trigger-rate penalty** but cap it at 0.35 (current implicit cap) and log the raw trigger rate in evidence for operator review.

---

## 2. Metric Balance

### Current state

| Threshold | Primary signal | Secondary |
|-----------|----------------|-----------|
| Efficiency | `hit_rate_promotions` | None |
| Stop quality | `aligned_pct` | None |

### Problem

Promotion hit rate is the right *north star* for Hermes, but efficiency reactions also affect **scope size, research throughput, and stop behavior**. A threshold tuned only on hit rate may fire during benign efficiency dips that do not harm outcomes.

### Recommendations

Use a **small multi-metric composite** (still explainable):

**Efficiency threshold candidate score:**

```
score = 0.45 × hit_rate_separation
      + 0.25 × maturity_separation
      + 0.15 × realized_r_separation (if n≥5 trades in window)
      + 0.15 × (1 - trigger_rate_penalty)
```

**Stop quality candidate score:**

```
score = 0.40 × alignment_separation
      + 0.30 × trail_delta_separation
      + 0.20 × maturity_stop_quality_separation
      + 0.10 × (1 - trigger_rate_penalty)
```

Require each component to be non-negative before proposing a loosening move.

---

## 3. Evidence Quality

### Current evidence payload

```json
{
  "sample_days": 22,
  "best_candidate_score": 0.0412,
  "candidate_metrics": { "separation": 0.08, "trigger_rate": 0.18 }
}
```

### Gaps

- No confidence tier
- No regime breakdown
- No comparison to current threshold's score (only best candidate)
- No explicit "why not other candidates" summary

### Recommendations

Enrich every proposal with:

```json
{
  "confidence": "medium",
  "confidence_factors": [
    "sample_days=22 ≥ min 14",
    "regime_stable=true",
    "second_best_candidate_within_0.01=true"
  ],
  "current_threshold_score": 0.038,
  "proposed_threshold_score": 0.041,
  "score_delta": 0.003,
  "runner_up": { "value": 0.48, "score": 0.040 },
  "regime_breakdown": {
    "normal_days": 18,
    "high_vol_days": 4
  },
  "metric_contributions": {
    "hit_rate_separation": 0.025,
    "maturity_separation": 0.010
  }
}
```

**Confidence tiers:**

| Tier | Criteria |
|------|----------|
| `low` | <14 sample days OR regime shift OR runner-up within 0.005 |
| `medium` | 14–21 days, stable regime |
| `high` | ≥22 days, stable regime, score_delta ≥ 0.005 |

Display confidence in the Closed Loop review modal.

---

## 4. Edge Cases

### Sparse data (14–20 days)

**Current:** hard floor at 14 days via `min_history_days`; per-threshold minimum 8 usable points.

**Recommendation:**

- Below 20 days: only allow proposals with `confidence: low` and max_step reduced by 50%
- Add explicit `sparse_data: true` flag in proposal
- UI shows amber banner: "Limited history — consider waiting for more nightly runs"

### Regime shifts during window

**Current:** no regime awareness in learner.

**Recommendation (Phase 1.5 — low complexity):**

1. Tag each trend point with `regime_label` if available from governor feed history
2. If >30% of window days are high-vol: downgrade confidence one level
3. Optionally compute scores on `normal` days only; attach both full-window and normal-only scores to evidence

### No improvement found

**Current:** skip silently (`skipped` list).

**Recommendation:** write a `no_proposal` audit entry with best candidate score vs current — helps operators see the learner ran and chose not to move.

---

## 5. Concrete Improvements (Priority Order)

| # | Improvement | Effort | Impact |
|---|-------------|--------|--------|
| 1 | Multi-metric composite scoring (§2) | Medium | High |
| 2 | Richer evidence + confidence tier (§3) | Low | High |
| 3 | Asymmetric tighten vs loosen bars (§1) | Low | Medium |
| 4 | Early-detection lead term (§1) | Medium | Medium |
| 5 | Regime-aware confidence downgrade (§4) | Low | Medium |
| 6 | Sparse-data max_step halving (§4) | Low | Low |

---

## 6. Example — Refined Scoring Decision

**Scenario:** 24 days of bus history, stable regime, efficiency threshold currently 0.50.

**Analysis:**

| Candidate T | Hit sep | Maturity sep | Trigger rate | Composite |
|-------------|---------|--------------|--------------|-----------|
| 0.50 (current) | 0.06 | 0.02 | 22% | 0.038 |
| 0.47 (proposed) | 0.09 | 0.04 | 28% | 0.044 |
| 0.44 | 0.10 | 0.05 | 38% | 0.039 ← penalty kicks in |

**Decision:** Propose **0.47** (not 0.44 — excessive trigger rate).

**Reasoning (operator-facing):**

> When efficiency fell below 0.47, promotion hit rate averaged 31% vs 42% baseline (9pp separation). Maturity composite averaged 64 vs 71 (+7). Trigger rate 28% is within acceptable bounds. Confidence: **medium** (24 sample days, stable regime). Proposing tighten 0.50 → 0.47 (max step 0.03).

**Expected impact:**

> Earlier conservative promotion-gate tightening when yield weakens; estimated 1–2 additional reaction days per month without exceeding false-positive tolerance.

---

## 7. Honest Assessment

| Dimension | Rating | Notes |
|-----------|--------|-------|
| Explainability | ★★★★★ | Best feature of current design |
| Conservative bias | ★★★★☆ | Good; loosening needs tighter bar |
| Signal quality | ★★★☆☆ | Single-metric dominance limits precision |
| Sparse-data handling | ★★☆☆☆ | Binary cutoff; needs graduated response |
| Regime awareness | ★☆☆☆☆ | Not yet implemented in learner |
| Evidence richness | ★★★☆☆ | Adequate for CLI; needs confidence for UI trust |

**Bottom line:** Ship Phase 1 as-is for visibility and governance. Implement improvements #1–#3 before enabling automated bi-weekly learning runs without operator review.

---

**Related:** `HERMES_ADAPTIVE_THRESHOLD_LEARNING.md` · `HERMES_THRESHOLD_EVALUATION_ENGINE.md`