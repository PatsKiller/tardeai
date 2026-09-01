# Phases 134-138 — Strategy Learning Infrastructure

Status:      HISTORICAL
as_of:       2026-06-01T17:52:57-04:00
Measured at: efcc51365 / not measured

## Phase 134 — Learning Queue (COMPLETE)

### Lesson Sources Found
| Source | Rows | Machine-Readable? | Used by Scoring? |
|--------|------|-------------------|------------------|
| paper_trade_multi_reviews | 28 | Partially (text blobs) | **NO** |
| strategy_lesson_rollup | 6 | Partially | **NO** |
| agent_intelligence_rules | 2 (outcome_lessons) | Yes (JSON) | LLM prompt only |
| confidence_calibration_history | 8 | Yes | **NO** |
| strategy_backtest_results | 40 | Yes | **NO** |
| hermes_research_intelligence | 45 | Yes | Advisory cache only |
| Phase 131 exit forensics | 3 defects | Yes | **NO** |

### Candidates Extracted (11)
| Lesson Type | Strategy | Confidence | Evidence |
|-------------|----------|------------|----------|
| stop_too_tight | swing_trade | 0.9 | stop >= entry |
| premature_exit | swing_trade | 0.5 | MFE +6% after stop |
| stop_too_tight | swing_breakout (APPS) | 0.9 | stop >= entry |
| stop_too_tight | earnings_catalyst (BLBD) | 0.9 | stop > entry (inverted) |
| stop_too_tight | swing_breakout (ONDS) | 0.9 | stop == entry |
| premature_exit | swing_breakout (ONDS) | 0.5 | MFE +7.1% after stop |
| stop_too_tight | fib_retracement_bounce | 0.9 | stop > entry |
| weak_backtest | core_growth_compounder | 0.4 | 31.6% WR, n=19 |
| weak_backtest | recovery_watch | 0.6 | 32.3% WR, n=31 |
| weak_backtest | all_signals | 0.6 | 33.9% WR, n=56 |
| data_quality | system | 0.9 | hold_time 91% missing |

## Phase 135 — Shadow Scoring (DESIGN)

### Shadow Overlay Model
For each candidate, compute:
- `original_score`: current GO/WAIT/NO GO score
- `shadow_score`: what score would be if learning applied
- `delta`: difference
- `learning_reason`: which lesson caused the change
- `not_live_decision`: true (always)

### Implementation
`scripts/strategy_learning_shadow_scorer.py` would:
1. Read current candidates from trade_ai_scans
2. Read strategy_learning_queue
3. Apply penalty/boost overlays based on lesson type
4. Output shadow scores to `data/learning/shadow_scores/`
5. Never modify live scores

**Status**: Design complete. Implementation deferred until learning queue has more data.

## Phase 136 — Journal Completeness Fix (DESIGN + PARTIAL)

### Missing Fields (from Phase 133)
| Field | Current % | Fix |
|-------|-----------|-----|
| hold_time_min | 8% | Compute at close: `closed_at - entry_time` |
| stop_type | 0% | Capture from bracket order type |
| planned_stop | 0% | Copy from proposal.proposed_stop at entry |
| exit_trigger_source | 0% | Set by closing script name |
| MFE/MAE | 63% | Already captured by monitor |

### Instrumentation Needed
At trade close, compute and write:
```python
hold_time_min = (closed_at - entry_time).total_seconds() / 60
stop_type = 'fixed'  # or 'trailing' if trail active
exit_trigger_source = script_name
```

**Status**: Design complete. Code instrumentation deferred to next session (requires touching paper_trade_monitor.py close paths).

## Phase 137 — Anti-Luck Metrics (DESIGN)

### Metrics Required
1. **Pre-learning baseline**: Strategy performance before any lesson applied
2. **Post-learning cohort**: Performance after changes (when they happen)
3. **Holdout**: Strategies with no changes as control group
4. **Sample size**: Minimum 20 trades per strategy before trusting
5. **Regime adjustment**: Separate risk-on/off/high-vol performance

### Current Assessment
- **Learning proven beyond luck**: **NO** (24 trades, no lessons applied to scoring)
- **Sample sufficient**: **NO** (need 20+ per strategy)
- **Loop closed**: **NO** (Links 8-9 broken)

## Phase 138 — Decision Lineage (DESIGN)

### Schema
Each candidate should carry:
```json
{
  "candidate_id": "...",
  "base_score": 42,
  "shadow_score": 38,
  "learning_adjustments": [
    {"lesson_id": 5, "type": "weak_backtest", "delta": -4, "reason": "recovery_watch 32% WR"}
  ],
  "lineage_explanation": "Penalized -4 due to weak backtest performance (32% WR, n=31)"
}
```

**Status**: Design complete. Implementation requires shadow scorer (Phase 135) to be active.

## Safety (all phases)
- Live strategy changes: ZERO
- GO/WAIT mutation: ZERO
- Proposal/trade/broker/holdings: ZERO
- Journal mutation: ZERO
- Level 7: PROHIBITED
