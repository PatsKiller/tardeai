# ATM Lifecycle API Coverage Report

**Captured:** 2026-05-26  
**Server:** http://127.0.0.1:7777  
**All endpoints returned HTTP 200.**

---

## Endpoint Inventory

| Endpoint | Lifecycle Stage | Key Fields Exposed |
|----------|----------------|-------------------|
| `/api/v2/atm/status` | Mode & State Control | mode, paused_until, pause_reason, last_state_change_at/by, is_market_hours, next_expected_cycle, accounts[].positions_open/new_today, decisions_today, classifier_guardrail |
| `/api/v2/atm/strategy-health` | Strategy Eligibility | strategy_id, classifier_health, has_baseline, closed_trades, wins, avg_r, eligible, bucket2_excluded, same_day_skip |
| `/api/v2/atm/queue-preview` | Execution Queue | (empty at capture -- shows pending orders awaiting fill) |
| `/api/v2/atm/decisions?limit=10` | Decision Audit Trail | id, decided_at, proposal_id, symbol, strategy_id, target_account, decision (approved/rejected/deferred), rejection_reasons[], classifier_health, positions_open, daily_pnl_pct, b1_excluded, config_hash, atm_mode, trade_id |
| `/api/v2/atm/config` | Configuration | version, defaults, same_day_skip_strategies, accounts, global limits, b1_tracking, config hash |
| `/api/v2/execution-integrity` | Operational Integrity | summary (ok/stale/missing/failed), checks[] per component (status, schedule, last_success/failure, severity, downstream_impact), recent_events[], safe_flock stats, time_stop_summary, alert_routing |
| `/api/v2/execution-quality` | Trade Cost Analysis (TCA) | per-fill: intended_entry, fill_price, arrival_price, slippage_pct/dollars, fill_quality grade, spread_pct, liquidity_context, time_to_fill, partial_fill, readiness/lifecycle/action states |
| `/api/v2/paper-proposals?limit=10` | Proposal Pipeline | proposals[], expired_today[], summary (pending/ready/stale/entry_missed/expired), incubator_diagnostics, by_strategy breakdown, portfolio_value |
| `/api/v2/system-health` | Infrastructure Health | LLM providers (spend/budget), db_tables row counts, cio_decisions distribution, cron_jobs count, finviz_screeners, validation_suites, data_freshness per product |
| `/api/v2/alerts` | Alert Surface | count, alerts[].id/type/severity/symbol/source_script/raw_text/created_at/parsed_payload |
| `/api/v2/strategy-intelligence` | Strategy Governance | per-strategy: governance_state, trade_count, win_rate, profit_factor, avg_r, expectancy, trades_to_validation, yaml completeness flags, co_enables, performance_verdict |
| `/api/v2/agent-collaboration` | Agent Coordination | summary (missions, blocked, stale, trust_state), john_next_actions[], mission_groups[], agent_network graph, scoring metrics, handoff_details[], agent_quality[], stale_products[], raci_health[] |
| `/api/v2/ops/cron-health` | Cron Monitoring | crons[].name/display_name/schedule/critical/status/runs_today |

---

## Lifecycle Stage Mapping

| Lifecycle Stage | Covered By | Coverage Level |
|----------------|-----------|---------------|
| 1. Signal Generation / Screening | `strategy-intelligence`, `system-health` (finviz_screeners) | Partial -- no raw signal feed |
| 2. Proposal Creation | `paper-proposals` | Full |
| 3. Enrichment & Scoring | `paper-proposals` (status tracking), `atm/decisions` (rejection_reasons) | Moderate |
| 4. ATM Decision Gate | `atm/decisions`, `atm/status`, `atm/config` | Full |
| 5. Strategy Eligibility | `atm/strategy-health`, `strategy-intelligence` | Full |
| 6. Order Submission | `atm/queue-preview` | Full (when active) |
| 7. Fill & TCA | `execution-quality` | Full |
| 8. Position Management | `execution-integrity` (time_stop_summary) | Partial |
| 9. Exit / Close | -- | **NO DIRECT API** |
| 10. Post-Trade Journal | -- | **NO DIRECT API** |
| 11. Strategy Governance / Graduation | `strategy-intelligence` (governance_state, trades_to_validation) | Moderate |
| 12. Agent Coordination | `agent-collaboration` | Full |
| 13. Operational Health | `execution-integrity`, `system-health`, `cron-health`, `alerts` | Full |

---

## Lifecycle Stages with NO API Coverage

| Stage | What's Missing | Impact on Control Room |
|-------|---------------|----------------------|
| **Exit / Close Decisions** | No endpoint showing pending exit signals, stop-loss triggers, time-stop actions taken, or close-order status | Cannot see why/when positions are being closed in real-time |
| **Post-Trade Journal** | No endpoint exposing trade journal entries, R-multiple outcomes, or lessons-learned per trade | Cannot audit closed-trade learning loop from dashboard |
| **Raw Signal Feed** | No endpoint for pre-proposal screener signals (what was scanned, what passed/failed filters) | Cannot trace signal-to-proposal funnel |

---

## Missing Fields for a Control-Room Dashboard

| Category | Missing Field / Data | Which Endpoint Should Carry It |
|----------|---------------------|-------------------------------|
| Position State | Current P&L per position, unrealized gain/loss, % of stop | Needs `/api/v2/positions` or extend `atm/status` |
| Position State | Entry time, hold duration, time-stop countdown | `execution-integrity` has overdue list but no countdown per position |
| Exit Signals | Active stop-loss prices, trailing stop state, news-exit triggers | Needs `/api/v2/stops` or `/api/v2/exit-signals` |
| Order State | Live order status (submitted/partial/filled/cancelled), order age | `queue-preview` was empty; needs richer order lifecycle fields |
| Fill Timing | `order_submitted_at`, `order_filled_at`, `time_to_fill_seconds` | Present in `execution-quality` schema but all null in sample |
| Proposal Funnel | Conversion rate (proposals -> approved -> filled -> profitable) | Needs aggregation endpoint or extend `paper-proposals` summary |
| Daily P&L | Aggregate daily P&L across accounts, high-water mark | Not exposed; only `daily_pnl_pct` in decisions |
| Classifier | Detailed classifier scores per symbol, feature importance | Only aggregate `classifier_health` float exposed |
| Alert Acknowledgment | Which alerts have been seen/dismissed/actioned by operator | `alerts` has no ack/dismiss state |
| Historical Mode Changes | ATM mode history (active/paused timeline) | `atm/status` only shows current + last change |

---

## Endpoints That Returned Errors

**None.** All 13 endpoints returned HTTP 200 with valid JSON.

---

## Files Captured

```
docs/atm_lifecycle_v1_2026_05_26/api_samples/
  atm_status.json
  atm_strategy_health.json
  atm_queue_preview.json
  atm_decisions.json
  atm_config.json
  execution_integrity.json
  execution_quality.json
  paper_proposals.json
  system_health.json
  alerts.json
  strategy_intelligence.json
  agent_collaboration.json
  cron_health.json
  API_LIFECYCLE_COVERAGE.md
```
