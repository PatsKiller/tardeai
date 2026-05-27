# Full Lifecycle Implementation Backlog

## v3.1 — Prospect & Research Control
- Unified prospect discovery page
- Signal traceability (candidate_id → signal_id)
- Research freshness gate on proposals
- Scorecard breakdown view

## v3.2 — Signal/Proposal Traceability
- Deduplicate proposal pipeline (29 duplicates)
- Per-proposal gate audit in API
- Proposal → decision → trade FK chain completion
- Decision backfill into lifecycle_events

## v3.3 — Approval/Risk Gate Workspace
- Unified risk dashboard with concentration, heat, sector caps
- Per-proposal gate pass/fail view
- Cash basis real-time tracking
- Classifier health graduation countdown

## v3.4 — Execution/Fill/Slippage Workspace
- Order lifecycle state machine (submitted → partial → filled → cancelled)
- TCA timing field population
- Fill quality near-real-time (not just EOD)
- Extended hours order logic visibility

## v3.5 — Stop/Trailing/Time-Stop Workspace
- Broker stop proof panel (Alpaca API read-only)
- Per-position trailing tier history
- Time-stop enforcement workflow (auto-alert for intraday held overnight)
- Stop replacement audit trail

## v3.6 — Journal/Learning/Backtesting Workspace
- Unified journal with R-multiple outcomes
- Backtest vs paper/live comparison
- Learning feedback dashboard
- Agent calibration visibility

## v3.7 — Unified Lifecycle Inspector
- Single-trade drilldown across all pages
- Lifecycle timeline visualization
- Cross-page navigation via lifecycle_id
- Consolidated workspace replacing 82 scattered routes
