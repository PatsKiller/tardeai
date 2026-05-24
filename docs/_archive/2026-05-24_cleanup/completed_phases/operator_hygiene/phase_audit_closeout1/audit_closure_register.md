# AUDIT-CLOSEOUT-1 — Full MCP Audit Closure Register

**Date:** 2026-05-20
**Audit source:** 43 live MCP route audits
**Unclassified items: 0**

## FIXED_VERIFIED (19 items)

| # | Item | Commit | Evidence |
|---|------|--------|----------|
| 1 | Self-Improvement render zeros | 53051af | No status?.data double-unwrap, holdings $1.19M |
| 2 | Risk-Regime "No snapshot" | 53051af | No regime?.data, shows high_volatility 43% |
| 3 | Retirement non-held labels | efa9401 | NOT HELD — RESEARCH ONLY badge present |
| 4 | Q-1C quote writeback | 6be6f2c | unknown_quote=0, Alpaca prices on proposals |
| 5 | AI brief stale badge | efa9401 | STALE badge for >24h reports |
| 6 | AI brief date context | 6be6f2c | TODAY'S DATE in LLM prompt |
| 7 | Forecast not Returns | 5cb0c91 | "not activated yet" placeholder |
| 8 | Journal-analytics tab | 5cb0c91 | Redirects with tab=analytics |
| 9 | Journal-reports tab | 5cb0c91 | Redirects with tab=reports |
| 10 | Content-health tab | 5cb0c91 | Redirects with tab=content-health |
| 11 | Learning-governance tab | 5cb0c91 | Redirects with tab=learning |
| 12 | Broker-recon route | 5cb0c91 | Redirects to broker-reconciliation |
| 13 | System-hub route | 5cb0c91 | Redirects to /v2/ops |
| 14 | ATP-4 quote-age stale | ef2e60c | Staleness policy checks quote age |
| 15 | ATP-4B counter alignment | 5e0990a | UNKNOWN_QUOTE increments Need Action |
| 16 | ATP-5 promoter gate | 58b263f | quote_never_checked blocks promotion |
| 17 | Pipeline false nominal | d902e5f+ | Never-run stages counted as warnings |
| 18 | Pipeline telemetry wrappers | 2e62921 | 8 wrappers emit pipeline_runs |
| 19 | Pipeline owner map | a2d908f | 31 stages with ownership metadata |

## DIAGNOSED_WITH_NEXT_PHASE (6 items)

| # | Item | Finding Doc | Next Phase |
|---|------|-------------|------------|
| 20 | Overnight template fallback | docs/_findings/overnight_template_fallback_2026-05-20.md | LLM-FIX-1 |
| 21 | Agent queue stuck | docs/_findings/agent_queue_stuck_2026-05-20.md | AGENT-FIX-1 |
| 22 | Attribution benchmark N/A | docs/_findings/attribution_benchmark_2026-05-20.md | ATTR-1 |
| 23 | Risk-regime cron stale | docs/_findings/risk_regime_cron_stale_2026-05-20.md | REGIME-CRON-1 |
| 24 | Count drift | docs/_findings/count_drift_2026-05-20.md | COUNT-TRUTH-1 |
| 25 | Pipeline remaining telemetry | docs/_findings/pipeline_remaining_telemetry_2026-05-20.md | PIPE-OBS-3 |

## WORKING_NO_ACTION (15 items)

| # | Route | Status |
|---|-------|--------|
| 26 | /v2/overview | Working |
| 27 | /v2/portfolio | Working |
| 28 | /v2/trade-ai | Working (1,415 tickers) |
| 29 | /v2/paper-proposals | Working (2 pending, 0 unknown) |
| 30 | /v2/recovery | Working |
| 31 | /v2/risk | Working |
| 32 | /v2/watchlist | Working |
| 33 | /v2/ai-analyst | Working (stale badge applied) |
| 34 | /v2/research | Working |
| 35 | /v2/strategy-admin | Working |
| 36 | /v2/paper-governance | Working |
| 37 | /v2/orchestration | Working |
| 38 | /v2/journal | Working |
| 39 | /v2/dividends | Working |
| 40 | /v2/returns | Working |

## OPERATOR_REQUIRED (2 items)

| # | Item | Decision Needed |
|---|------|-----------------|
| 41 | Rebalance data 36 days stale | Requires API credits or manual refresh |
| 42 | Brave Search depleted | Requires API key top-up |

## EMPTY_BY_DESIGN (1 item)

| # | Route | Reason |
|---|-------|--------|
| 43 | /v2/backtesting | Feature not yet activated |
