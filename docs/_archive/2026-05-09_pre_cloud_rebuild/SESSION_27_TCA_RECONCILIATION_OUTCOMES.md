# Session 27: TCA Dashboard + Broker Reconciliation + Paper Outcome Analytics
**Date:** 2026-05-08
**Scope:** Execution quality, broker reconciliation, thesis outcomes, paper governance — all with zero-closed-trade empty states

## What Was Built

### 1. Schema Hardening
- `paper_execution_quality`: +14 columns (time_to_fill, partial_fill, market_session, readiness/lifecycle/action state at submit, data_quality_grade, etc.)
- `broker_reconciliation_items`: +8 columns (local/broker status/qty/price, severity, recommended_action)
- `trade_thesis_outcomes`: +10 columns (MFE/MAE, time_in_trade, exit_reason, thesis_followed, strategy_fit/catalyst/technical/agent/llm at entry)
- `paper_dashboard_snapshots`: NEW table for time-series dashboard data

### 2. API Endpoints (5 existing + 4 new)

| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v2/execution-quality` | GET | Existing — returns TCA rows |
| `/api/v2/execution-quality/run` | POST | Existing — triggers analyzer |
| `/api/v2/broker-reconciliation` | GET | Existing — returns recon runs + items |
| `/api/v2/broker-reconciliation/run` | POST | Existing — triggers reconciler |
| `/api/v2/paper-performance-governance` | GET | Existing — returns governance rows |
| `/api/v2/paper-outcomes` | GET | **NEW** — thesis outcomes + open/closed counts |
| `/api/v2/paper-outcomes/run` | POST | **NEW** — triggers thesis reviewer |
| `/api/v2/paper-performance-governance/run` | POST | **NEW** — triggers governance calculator |
| `/api/v2/paper-dashboard-summary` | GET | **NEW** — consolidated dashboard summary |

### 3. Frontend Pages

| Page | Route | Status |
|------|-------|--------|
| Execution Quality | `/v2/execution-quality` | Existing — TCA data grid |
| Broker Reconciliation | `/v2/broker-reconciliation` | Existing — recon runs + items |
| Paper Outcomes | `/v2/paper-outcomes` | **Updated** — added thesis outcomes, open monitoring, run button |
| Paper Governance | `/v2/paper-governance` | **NEW** — governance dashboard with gate checklist |

### 4. Paper Governance Dashboard
- Red "LIVE TRADING DISABLED" banner
- Summary metric tiles (open trades, closed trades, strategies, live eligible: 0)
- Gate checklist: 6 months, 30 closed trades, win rate >= 55%, profit factor >= 1.3, positive expectancy, TCA acceptable, broker recon clean, human approval — all NOT MET
- Strategy scorecards table
- "Run Governance Check" button
- Clean empty state when no closed trades

### 5. Paper Outcomes Updates
- Thesis outcomes table (symbol, strategy, verdict, entry thesis, outcome notes, PnL, R multiple)
- Open monitoring section with open/closed/awaiting review counts
- "Run Thesis Outcome Review" button
- Dashboard summary integration

## Data Model

### Execution Quality Metrics
- `intended_entry`, `submitted_limit_price`, `arrival_price`, `fill_price`
- `spread_pct`, `slippage_pct`, `slippage_dollars`, `price_improvement_pct`
- `time_to_fill_seconds`, `partial_fill`, `fill_quality` (EXCELLENT/GOOD/ACCEPTABLE/POOR/UNKNOWN)
- `market_session`, `readiness_state_at_submit`, `packet_completion_pct_at_submit`

### Broker Reconciliation States
MATCHED, BROKER_ORDER_NO_LOCAL_TRADE, LOCAL_TRADE_NO_BROKER_ORDER, POSITION_SIZE_MISMATCH, STATUS_MISMATCH, PRICE_MISMATCH, CANCELED_OK, REJECTED_OK, CLOSED_OK, UNKNOWN

### Paper Outcome Labels
THESIS_CONFIRMED, THESIS_PARTIAL, THESIS_FAILED, EXECUTION_ERROR, DATA_INSUFFICIENT, OPEN_MONITORING

### Governance States
PAPER_ONLY, LEARNING_MODE, WATCHLIST, CANDIDATE_FOR_REVIEW, LIVE_ELIGIBLE_REVIEW_REQUIRED

### Governance Gates (all must pass)
1. >= 6 calendar months observed
2. >= 30 closed paper trades per strategy
3. Win rate >= 55%
4. Profit factor >= 1.3
5. Positive expectancy
6. TCA acceptable
7. Broker reconciliation clean
8. Human approval required

## Empty-State Behavior
- All endpoints return `{"ok": true, ...}` with zero counts
- All pages render gracefully with "No data yet" messages
- No fake statistics generated
- Learning-mode warnings for low sample sizes
- `live_eligible` is always `false` (hardcoded)

## Validation
- 27/27 checks passed
- All scripts import and dry-run cleanly
- All API endpoints return ok
- Frontend build passes
- Holdings: $1,189,457 untouched
- Live trading: disabled
- Real journal: clean
- No generated artifacts staged

## Current State
- Open paper trades: 2
- Closed paper trades: 0
- Execution quality rows: 2
- Reconciliation issues: 0
- Outcome reviews: 0
- Strategies in learning mode: 5
- Live eligible strategies: 0

## Next Steps
- Session 28: Paper execution submit/reconcile controlled test + closing workflow
- Need closed paper trades to test thesis-vs-outcome reviewer
- Need more paper trades to accumulate governance statistics
