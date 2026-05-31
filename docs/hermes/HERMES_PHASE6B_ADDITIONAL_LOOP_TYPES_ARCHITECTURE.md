# Hermes Phase 6B — Additional Loop Types Architecture

**Date:** 2026-05-31
**Status:** DESIGN ONLY — no activation

---

## Current Active Loop

| Loop | Schedule | Cap | Status |
|------|----------|-----|--------|
| Ticker Challenger | Daily 01:00 UTC | 2 rows/run | ACTIVE |

---

## Proposed Additional Loops

### 1. Pipeline Quality Loop

| Parameter | Value |
|-----------|-------|
| Purpose | Detect stale data, pipeline failures, scoring drift |
| Schedule | Twice daily: 12:00, 20:00 UTC |
| Reads | hermes_v_pipeline_health_context, system_health_checks, daily_system_metrics |
| Writes | hermes_validation_findings, hermes_alerts |
| Cap | 3 rows/run |
| Model | gemma3:4b (lightweight) |
| Forbidden | production tables, broker, execution |

### 2. Overnight Portfolio Reflection Loop

| Parameter | Value |
|-----------|-------|
| Purpose | Review closed trades, extract lessons, identify patterns |
| Schedule | Daily 02:00 UTC (after ticker challenger) |
| Reads | hermes_v_trade_reflection_context, hermes_v_portfolio_context, hermes_v_ticker_context |
| Writes | hermes_research_intelligence |
| Cap | 2 rows/run |
| Model | gemma3:12b |
| Forbidden | production tables, broker, execution |

### 3. Promotion Review Loop

| Parameter | Value |
|-----------|-------|
| Purpose | Review staged rows, score quality, flag promotion candidates |
| Schedule | Weekly Sunday 03:00 UTC |
| Reads | hermes_research_intelligence, hermes_promotion_audit |
| Writes | hermes_validation_findings (quality scores only) |
| Cap | 5 rows/run |
| Model | gemma3:4b |
| Forbidden | auto-promotion, production tables, broker |

### 4. Source Discovery Loop (internal-only)

| Parameter | Value |
|-----------|-------|
| Purpose | Identify new research-worthy tickers from safe views |
| Schedule | Weekly Sunday 04:00 UTC |
| Reads | hermes_v_ticker_context, hermes_v_trade_reflection_context, intelligence_entities |
| Writes | hermes_memory_events |
| Cap | 3 rows/run |
| Model | gemma3:4b |
| Forbidden | external APIs, web browsing, production tables |

---

## Caps Summary (all loops combined)

| Cap | Value |
|-----|-------|
| Daily rows (all loops) | 10 |
| Daily model calls | 15 |
| Max runtime per loop | 600s |
| Kill switch | hermes_sidecar/.hermes/DISABLED (stops ALL loops) |

## Approval Gates

| Loop | Gate | Status |
|------|------|--------|
| Pipeline Quality | Phase 7A manual dry-run | NOT STARTED |
| Portfolio Reflection | Phase 7B manual dry-run | NOT STARTED |
| Promotion Review | Phase 7C manual dry-run | NOT STARTED |
| Source Discovery | Phase 7D manual dry-run | NOT STARTED |

Each loop requires: dry-run → manual apply → timer activation → observation review.

## Recommended Activation Order

1. Pipeline Quality (simplest, gemma3:4b, validation only)
2. Portfolio Reflection (builds on existing trade reflection)
3. Promotion Review (weekly, low-risk)
4. Source Discovery (internal-only first)
