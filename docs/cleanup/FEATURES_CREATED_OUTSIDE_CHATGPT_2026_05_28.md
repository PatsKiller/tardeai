# Features Created Outside ChatGPT (by Claude Code) - 2026-05-28

This document tracks features and components built by Claude Code sessions (not ChatGPT), which may not appear in the original ChatGPT project plan. These should be treated as active, canonical work.

---

## v4.0 Recurring Backtest / LLM Coverage

- **Implementation Report:** `docs/atm_lifecycle_v1_2026_05_26/V4_0_RECURRING_BACKTEST_LLM_COVERAGE_IMPLEMENTATION_REPORT.md`
- **Design directory:** `docs/atm_lifecycle_v1_2026_05_26/backtest_llm_coverage_v4_0_design/`
- **Status:** Implemented 2026-05-28. Recurring backtest cron with LLM trade analysis coverage.
- **Key files:** BACKTEST_LLM_COVERAGE_V4_0_DESIGN.md, RECURRING_BACKTEST_CRON_DESIGN.md, LLM_BACKTEST_TRADE_ANALYZER_DESIGN.md
- **Note:** Built entirely outside ChatGPT plan. Treat as active.

## Command Center / Agent Page Documentation

- `docs/COMMAND_CENTER_PAGE_MATRIX.md` (9,944 bytes, 2026-05-27) -- Page matrix for all Command Center views
- `docs/AGENT_PAGES_DETAIL.md` (12,667 bytes, 2026-05-27) -- Detailed agent page specifications
- Built by Claude Code during UI redesign sessions

## Broker Adapters

- **schwab_adapter.py** -- Schwab broker adapter scaffolding
- **tastytrade_adapter.py** -- Tastytrade broker adapter scaffolding
- **broker_config.py** -- Central broker configuration module (canonical source for account config)
- 8 brokers configured, 2 adapter scaffoldings

## Trade Execution Analyzer

- **trade_execution_analyzer.py** -- MFE/MAE (Maximum Favorable/Adverse Excursion) analysis
- Provides execution quality metrics for trade performance measurement

## Stop Change Audit

- **stop_change_audit.py** -- Audit trail for all stop price changes
- UI panel in ATM Control Room (StopProofPanel)
- API endpoint: /api/atm/stop-change-audit

## Claude Escalation Handler

- **claude_escalation_handler.py** -- 3-tier escalation: Python self-heal -> Claude Code -> LLM nightly review
- Integrated with health agent pipeline

## Health Agent LLM Review

- **health_agent_llm_review.py** -- Nightly LLM review of health agent findings
- Part of 3-tier escalation system
- 26 monitored components with self-heal capabilities

## Agent Lifecycle Page (100% Rebuild)

- Complete rebuild of the Agent Lifecycle page
- Documented in AGENT_PAGES_DETAIL.md
- Built entirely by Claude Code sessions

## Command Center Redesign

- Full redesign with new page matrix
- 17 pages, 5 UI primitives, 11 API fields
- Documented in SESSION_2026_05_27.md and UI redesign session notes

## Agent Pipeline Redesign

- Pipeline monitoring and health dashboard
- Integrated with 26-monitor health agent system
- Per-brief threads with agent maturity, schedule, and next pickup

## BrokerAccountAdmin Page

- Broker account administration interface
- Supports 8 configured brokers
- Uses broker_config.py as canonical source

## Health Agent Enhancements

- 26 monitored components
- Portfolio risk checks
- Self-heal capabilities for common failures
- Alert dedup: staleness 4h, proposals 30min, after-hours suppression
- 3-tier escalation system

## Live Price Validation (4-Layer Defense)

- 4 independent validation layers for price accuracy
- Prevents stale/incorrect price data from reaching trading decisions

## Alert Spam Fixes

- Alert deduplication with configurable staleness windows
- After-hours alert suppression
- Proposal alert rate limiting (30min window)

## Cron Pipeline Recovery

- Automatic cron health monitoring
- Self-heal for common cron failures
- Worker backlog guard

## Source Exports for Backtesting Scripts

- `docs/atm_lifecycle_v1_2026_05_26/source_exports/` -- 200+ source code snapshots
- Used as reference for backtesting script development
- Includes: enterprise_backtester, strategy_backtester, backtest_analyzer, trade_backtest_engine

---

## Summary

All items above were built by Claude Code, not by the ChatGPT-based project plan. They should be treated as active, canonical features of the system. Any cleanup or archive operation must preserve these files and their documentation.
