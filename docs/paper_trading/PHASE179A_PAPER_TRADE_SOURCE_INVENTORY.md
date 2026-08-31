# Phase 179A: Paper Trade Source Inventory

Status:      HISTORICAL
as_of:       2026-06-01T23:21:01-04:00
Measured at: efcc51365 / not measured

**Date**: 2026-06-01
**Operator**: John Whiting
**Mode**: PAPER ONLY — no live trading

## Paper Trade Data Sources

### Primary Table: `paper_trades`

| Field | Status |
|-------|--------|
| Table | `paper_trades` |
| Row count | 44 |
| Closed trades | 24 |
| Open trades | 6 |
| Cancelled | 14 |
| Timestamp range | 2026-05-06 to 2026-06-01 |
| Account mode | paper (broker='alpaca_paper' for 4, rest system) |
| Strategy field | YES — 100% populated |
| Entry/exit fields | entry_price 100%, exit_price 75% |
| Dollar amount | YES — dollar_size 100%, dollar_risk 96% |
| Journal linkage | trade_thesis_outcomes: 21 linked |
| Backtest linkage | backtest_quality: 0% populated |
| Hermes linkage | hermes_research_intelligence: 0 linked |

**Key columns**: id, symbol, strategy_id, account, entry_price, exit_price, shares, dollar_size, dollar_risk, stop_loss, target_1, target_2, r_multiple, pnl, pnl_pct, hold_time_min, exit_reason, close_reason, catalyst_at_entry, market_regime, vix_at_entry, max_adverse_excursion, max_favorable_excursion, broker_order_id, proposal_id, post_trade_analyzed, status, created_at, closed_at

### Proposals Table: `paper_trade_proposals`

| Field | Status |
|-------|--------|
| Table | `paper_trade_proposals` |
| Row count | 147 |
| Strategy field | YES |
| Entry/exit fields | YES (proposed_entry, proposed_stop, proposed_target1) |
| Dollar amount | YES (proposed_dollar_size, proposed_dollar_risk) |
| Execution tracking | paper_submit_state, paper_broker_order_id |

### Execution Quality: `paper_execution_quality`

| Field | Status |
|-------|--------|
| Table | `paper_execution_quality` |
| Row count | 23 |
| Links to | paper_trade_id, proposal_id |
| Fields | fill_price, slippage_pct, time_to_fill_seconds, fill_quality |

### Execution Events: `paper_execution_events`

| Field | Status |
|-------|--------|
| Table | `paper_execution_events` |
| Row count | 0 |

### Execution Quality Events: `paper_execution_quality_events`

| Field | Status |
|-------|--------|
| Table | `paper_execution_quality_events` |
| Row count | 41 |

### Outcome Analytics: `paper_trade_outcome_analytics`

| Field | Status |
|-------|--------|
| Table | `paper_trade_outcome_analytics` |
| Row count | 16 |
| Fields | r_multiple, exit_reason, followed_plan, outcome_verdict, lessons |

### Thesis Outcomes: `trade_thesis_outcomes`

| Field | Status |
|-------|--------|
| Table | `trade_thesis_outcomes` |
| Row count | 21 |
| Fields | thesis_result, thesis_followed, actual_r, time_in_trade_minutes |

### Performance Governance: `paper_performance_governance`

| Field | Status |
|-------|--------|
| Table | `paper_performance_governance` |
| Row count | 161 |
| Fields | win_rate, avg_r, profit_factor, max_drawdown_r, governance_state |

### Learning Memory: `trade_lesson_memory`

| Field | Status |
|-------|--------|
| Table | `trade_lesson_memory` |
| Row count | 10 |

### Hermes Research Intelligence: `hermes_research_intelligence`

| Field | Status |
|-------|--------|
| Table | `hermes_research_intelligence` |
| Related trade linkage | 0 trades linked |

### Broker Reconciliation

| Table | Rows |
|-------|------|
| `broker_reconciliation_runs` | exists |
| `paper_broker_reconciliation_runs` | 0 |
| `paper_broker_reconciliation_items` | 0 |

### ATM Decision Log

| Table | Rows |
|-------|------|
| `atm_decision_log` | 168 |
| `atm_close_actions` | 4 |
| `atm_overdue_position_decisions` | 12 |
| `atm_state` | 1 |

### Backtest Reference: `strategy_backtest_trades`

| Field | Status |
|-------|--------|
| Row count | 8,998 |
| Note | Backtest-only, not real paper trades |
| No linkage to paper_trades | Confirmed |

## Field Completeness Summary (24 Closed Trades)

| Field | Present | Pct |
|-------|---------|-----|
| strategy_id | 24 | 100% |
| entry_price | 24 | 100% |
| dollar_size | 24 | 100% |
| exit_reason | 24 | 100% |
| dollar_risk | 23 | 96% |
| stop_loss | 23 | 96% |
| target_1 | 23 | 96% |
| market_regime | 21 | 88% |
| vix_at_entry | 21 | 88% |
| proposal_id | 21 | 88% |
| exit_price | 18 | 75% |
| pnl | 18 | 75% |
| r_multiple | 16 | 67% |
| MAE | 15 | 62% |
| MFE | 15 | 62% |
| catalyst_at_entry | 13 | 54% |
| broker_order_id | 12 | 50% |
| close_reason | 9 | 38% |
| post_trade_analyzed | 4 | 17% |
| hold_time_min | 2 | 8% |
| backtest_quality | 0 | 0% |
| hermes_linkage | 0 | 0% |

## Critical Gaps

1. **hold_time_min**: Only 8% populated — must fix computation on close
2. **backtest_quality**: 0% — no backtest comparison running for paper trades
3. **hermes_linkage**: 0% — Hermes not auditing paper trades yet
4. **post_trade_analyzed**: 17% — overnight LLM analysis lagging
5. **catalyst_at_entry**: 54% — many trades lack catalyst context
6. **broker_order_id**: 50% — half the trades were system-generated without broker submission
7. **Sample size**: 24 closed trades is Level P0 — far from 2,000 target
