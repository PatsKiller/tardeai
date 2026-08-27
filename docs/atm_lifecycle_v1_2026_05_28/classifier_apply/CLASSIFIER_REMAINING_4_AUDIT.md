# Classifier — Remaining 4 Backtest Trades

**Date:** 2026-05-28

Targeted classification of 4 `strategy_backtest_trades` rows not reachable by the standard classifier query (which uses the `trades` view).

| ID | Symbol | Strategy | Confidence | Evidence | DB Updated |
|----|--------|----------|------------|----------|------------|
| 806 | V | dividend_growth_compounder | 0.9 | ticker=dividend_growth_compounder (1.0), watchlist=income | 1 row |
| 860 | SHFS | needs_review | 0.3 | No enrichment data | skipped |
| 874 | FJSCX | needs_review | 0.4 | watchlist=core_holding only | skipped |
| 875 | FJSCX | needs_review | 0.4 | watchlist=core_holding only | skipped |

**Deterministic classification** — no LLM called. V had strong enrichment (2 sources). SHFS and FJSCX lacked sufficient evidence.

**Remaining unclassified:** 3 (SHFS, FJSCX x2) — pending additional enrichment data.
