# Phase 133 — Closed-Loop Learning Lineage Audit

Status:      HISTORICAL
as_of:       2026-06-01T17:47:21-04:00
Measured at: efcc51365 / not measured

## The Question
Is TradeAI truly learning from journal/backtest outcomes, or merely reporting results?

## Learning Loop — Link-by-Link Audit

### Link 1: Candidate → Strategy Signal ✓ WORKS
- `trade_ai_orchestrator.py` → `trade_ai_scans` (491 signals)
- Strategy classification assigns strategies to candidates
- GO/WAIT/NO GO computed from score + RVOL + catalyst + enrichment

### Link 2: Signal → Proposal ✓ WORKS
- `auto_proposal_generator.py` creates proposals from signals
- 147 proposals created, enriched via 8-stage pipeline
- ATM auto-approver evaluates PENDING proposals every 15 min

### Link 3: Proposal → Trade ✓ WORKS
- `proposal_paper_submitter.py` creates bracket orders
- 24 closed trades with entry/exit data
- Stop quality guards added in Phase 131

### Link 4: Trade → Exit Capture ⚠ PARTIALLY BROKEN
- **exit_reason**: 24/24 now populated (Phase 121 fix)
- **closed_via**: 23/24 populated (1 blank)
- **pnl**: 18/24 populated (75%) — 6 trades have no P&L
- **r_multiple**: 16/24 populated (67%)
- **MFE/MAE**: 15/24 populated (63%)
- **hold_time_min**: 2/24 populated (**8% — nearly all missing**)
- **entry_time**: 19/24 populated (79%)
- **Defects found**: 2 trades had stop==entry (Phase 131), 1 had inverted stop

### Link 5: Exit → Postmortem ✓ WORKS
- `multi_tier_trade_reviewer.py` generates postmortems
- 28 reviews exist for 24 trades (some multi-tier)
- Reviews include lesson text and stop analysis

### Link 6: Postmortem → Backtest Comparison ⚠ WEAK
- 40 backtest results exist across strategies
- `strategy_lesson_rollup` has 6 entries
- **No automated backtest-vs-live comparison exists**
- Backtest and live results live in different tables with no automated reconciliation
- An operator can compare manually via the backtesting dashboard, but the system doesn't do it

### Link 7: Comparison → Learning Recommendation ⚠ EXISTS BUT DISCONNECTED
- `agent_intelligence_rules` has 67 rules including "outcome_lessons"
- `confidence_calibration_history` has 8 rows
- `decision_outcome_log` appears empty or not actively written
- Lessons are written but stored as text blobs, not machine-actionable parameters

### Link 8: Recommendation → Strategy Config Change ✗ **BROKEN**
- **No automated path exists from lessons to strategy config**
- `strategy_lesson_rollup` is read by the API for display only
- `agent_intelligence_rules` lessons are injected into LLM prompts as context but do NOT change scoring thresholds, stop rules, or candidate filters
- Strategy YAML configs (`config/strategies/*.yaml`) are never updated by the learning system
- The orchestrator does NOT read lessons before scoring

### Link 9: Config Change → Next Trade Influenced ✗ **NOT PROVEN**
- Since Link 8 is broken, Link 9 cannot be proven
- Next-trade scoring uses the same static YAML configs regardless of prior outcomes
- No "decision lineage" field on proposals or trades showing "boosted/demoted because of prior outcome"

## Journal Completeness Score

| Field | Present | % | Status |
|-------|---------|---|--------|
| exit_reason | 24/24 | 100% | Fixed (Phase 121) |
| strategy_id | 24/24 | 100% | OK |
| closed_via | 23/24 | 96% | OK |
| entry_time | 19/24 | 79% | Weak |
| pnl | 18/24 | 75% | Weak |
| r_multiple | 16/24 | 67% | Weak |
| MFE/MAE | 15/24 | 63% | Weak |
| hold_time_min | 2/24 | **8%** | **CRITICAL** |
| **Overall** | | **65%** | **Incomplete** |

## Backtest/Live Alignment

Cannot be scored — no automated comparison exists. Manual inspection shows:
- Backtest classification 3,593/3,593 complete
- Live trades: 24 closed
- No table/view joins backtest results to live trade outcomes for the same strategy

## Is the System Learning Beyond Luck?

**NO — not provably.**

Evidence of learning infrastructure:
- ✓ Postmortems generated
- ✓ Lessons written to DB
- ✓ Calibration scores exist
- ✓ Backtests run weekly

Evidence the loop is NOT closed:
- ✗ Lessons don't change strategy configs
- ✗ Orchestrator doesn't read lessons before scoring
- ✗ No "decision lineage" on next trades
- ✗ Hold time not captured (8% populated)
- ✗ No backtest-vs-live reconciliation
- ✗ No holdout comparison
- ✗ Sample size (24 closed trades) too small for statistical proof

## Where the Loop is Broken

```
candidate → signal → proposal → trade → exit → postmortem → lesson
                                                                 ↓
                                                     STORED BUT NOT USED
                                                                 ↓
                                                     strategy config ← NOT CONNECTED
                                                                 ↓
                                                     next trade ← NOT INFLUENCED
```

## Hermes Learning Auditor Design (133E)

Hermes should:
1. Verify journal completeness after every trade close
2. Flag missing hold_time, pnl, MFE/MAE
3. Compare postmortem recommendations against strategy config
4. Detect if lessons are written but never acted on
5. Challenge sample-size-based strategy changes
6. Create learning backlog rows for unresolved recommendations
7. NOT directly mutate strategy configs

## Safety
- Strategy mutation: ZERO
- GO/WAIT mutation: ZERO
- Proposal writes: ZERO
- Trades: ZERO
- Broker access: ZERO
- Journal mutation: ZERO
- Holdings mutation: ZERO
- Level 7: PROHIBITED
