# v3.7 Unified Single-Trade Lifecycle Inspector

## Purpose
One inspector that answers every lifecycle question for any symbol/trade/proposal.
Aggregates all v3.1-v3.6 data sources into a single deep view.

## Current Data Sources (11 endpoints)
- lifecycle/trace-summary, lifecycle/trace
- atm/proposal-hygiene, atm/proposal-dedup
- atm/reconciliation-health
- atm/stop-proof, atm/stop-trailing-control, atm/stop-change-audit
- atm/execution-timing-health
- lifecycle/journal-learning-summary, lifecycle/trade-case-study

## Proposed API
GET /api/v2/lifecycle/trade-inspector — aggregates all sources by identity.

## Proposed UI
UnifiedTradeInspector.tsx with 12 tabs: Overview, Source, Proposal, Risk/Approval,
Execution, Stops, Reconciliation, Journal, Learning, Backtest, Data Quality, Raw.

## Safety
- Read-only aggregate of existing endpoints
- No writes, no orders, no broker actions, no mutations
- Uses identity resolution: paper_trade_id > trace_id > proposal_id > symbol+strategy

## LLM Review Integration — v3.8 Forward Hook

v3.7 reserves an "LLM Review" tab in the inspector. v3.7 does NOT run LLMs.

The tab displays stored LLM review data if it exists:
- close_analysis_status: not_generated | complete | error
- delayed_review_status: not_generated | complete | error
- monthly_meta_review_status: not_generated | complete | error
- latest_llm_review_timestamp
- model_used
- confidence / data quality caveat
- key lessons (if generated)

If no LLM analysis exists, shows: "LLM review not yet generated for this trade."

v3.8 will implement the actual LLM analysis pipeline with three stages:
1. Close-of-trade analysis (local 3.14B LLM, at close)
2. Delayed post-close review (local LLM, ~1 week after close)
3. Monthly meta-review (Grok, monthly)

## What v3.7 Will NOT Do
- No new schema
- No new tables
- No trade actions
- No broker writes
- No backtest execution
- No LLM model calls
