# SCREENER-ARCH-2 Completion Matrix

| # | Deliverable | Status | Evidence | Deferred Phase |
|---|-------------|--------|----------|----------------|
| 1 | FinViz ingestion method audit | **DONE** | finviz_ingestion_method_audit_report.md | — |
| 2 | 50-row cap removed | **DONE** | No `tickers[:50]` in code | — |
| 3 | 500-row normal cap removed | **DONE** | No `tickers[:500]` in code | — |
| 4 | 5,000 emergency cap documented | **DONE** | MAX_ROWS_PER_SCREENER=5000 | — |
| 5 | Full CSV ingestion proven | **DONE** | ~41,000 rows, 2,973 new tickers | — |
| 6 | Capped screeners reported | **DONE** | 4 screeners at 5,000 documented | — |
| 7 | New ticker insertion cap raised | **DONE** | 10 → 200 per screener | — |
| 8 | Per-screener 10,000 override | **DEFERRED** | Needs per-screener config | SCREENER-ARCH-2B |
| 9 | Raw page metadata persistence | **DEFERRED** | Single CSV, no pages to track | SCREENER-ARCH-3 |
| 10 | Raw row persistence | **DEFERRED** | Rows go to trade_ai_scans | SCREENER-ARCH-3 |
| 11 | Ticker catalog table | **PARTIAL** | Uses existing watchlist_items + ticker_strategy_classifications | SCREENER-ARCH-3 |
| 12 | Screener membership lifecycle | **DEFERRED** | Design doc created, not implemented | SCREENER-ARCH-3 |
| 13 | Dropped/reentered lifecycle | **DEFERRED** | Design doc created, not implemented | SCREENER-ARCH-3 |
| 14 | Full universe strategy-fit audit | **DEFERRED** | Script not created | SCREENER-ARCH-4 |
| 15 | Stale screener remediation | **DEFERRED** | 8 stale identified, not fixed | SCREENER-ARCH-5 |
| 16 | After-close schedule | **DEFERRED** | Design doc created, cron not installed | SCREENER-ARCH-5 |
| 17 | Overnight schedule | **DEFERRED** | Design doc created, cron not installed | SCREENER-ARCH-5 |
| 18 | Premarket schedule | **DEFERRED** | Design doc created, cron not installed | SCREENER-ARCH-5 |
| 19 | Coverage alerts | **DEFERRED** | Not implemented | SCREENER-ARCH-5 |
| 20 | Dashboard coverage diagnostics | **DEFERRED** | Not implemented | SCREENER-ARCH-5 |
| 21 | Tests | **DONE** | 13/13 ARCH-2 + regression | — |
| 22 | Safety | **DONE** | Paper-only, no trades | — |

## Summary

**7 of 22 deliverables DONE.** 1 PARTIAL. **14 DEFERRED** to follow-up phases.

SCREENER-ARCH-2 delivered the critical ingestion fix (removing data-loss caps)
and proved the system can now ingest ~41,000 rows. The catalog, lifecycle,
strategy-fit, schedule, and coverage alert work requires dedicated phases.

## Deferred Phases

- **SCREENER-ARCH-2B**: Per-screener cap overrides for 4 broad ETF/income screeners
- **SCREENER-ARCH-3**: Ticker catalog + screener membership + dropped/reentered lifecycle
- **SCREENER-ARCH-4**: Full universe strategy-fit audit against all YAML strategies
- **SCREENER-ARCH-5**: Stale screener remediation + after-close/overnight/premarket schedule + coverage alerts
