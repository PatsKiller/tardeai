# Phases 138-140 — Lineage, Effectiveness, Observation

Status:      HISTORICAL
as_of:       2026-06-01T18:14:58-04:00
Measured at: efcc51365 / not measured

## Phase 138 — Decision Lineage (COMPLETE)
- 27 candidates processed
- 16 with learning links (59.3%)
- 11 without learning links
- Each shows: base_score, shadow_score, delta, lesson_ids, lesson_types, explanation
- swing_trade: 4 lessons (stop defects + premature exits) → -9 delta
- recovery_watch/core_growth: weak_backtest → -5 delta

## Phase 137 — Effectiveness Metrics (COMPLETE)
| Metric | Value |
|--------|-------|
| Learning proven | True (borderline) |
| Evidence strength | MODERATE |
| Luck risk | MEDIUM |
| Sample size | 24 (sufficient: True) |
| Loop closed | 59.3% |
| Shadow penalized | 16/27 |
| Journal completeness | 74.1% |
| Hold time completeness | 8.3% (CRITICAL) |
| Stop defects | 5 |
| Recommendations in live scoring | **NO** |

### Strategy Deltas
| Strategy | Avg Delta | Candidates |
|----------|-----------|------------|
| swing_trade | -9.0 | 8 |
| dividend_growth_compounder | -6.0 | 4 |
| core_growth_compounder | -5.0 | 3 |
| high_yield_income_bdc | -2.0 | 1 |

## Phase 140 — Observation Window (ACTIVE)
- Shadow scorer timer: `hermes-shadow-scorer.timer`
- Schedule: Mon-Fri 10 AM, 2 PM, 6 PM ET
- Output: `data/learning/shadow_scores/`
- First fire: Tue 2026-06-02 10:00 ET
- Observation period: 5 market days minimum before considering live scoring integration
- No live mutation

### Observation Criteria
- **Promote to live scoring** if:
  - Shadow deltas are consistent across 5+ sessions
  - No false-positive penalization of winning trades
  - Strategy-level recommendations stable (not oscillating)
  - Journal completeness improves above 80%
- **Reject/defer** if:
  - Shadow deltas oscillate session-to-session
  - Penalizations don't correlate with actual outcomes
  - Sample size still insufficient per strategy

## Safety
- Live strategy changes: ZERO
- GO/WAIT mutation: ZERO
- Proposal/trade/broker/holdings: ZERO
- Level 7: PROHIBITED
