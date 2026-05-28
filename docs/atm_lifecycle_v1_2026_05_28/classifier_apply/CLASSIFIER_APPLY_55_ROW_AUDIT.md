# Classifier Apply 55-Row Audit

**Date:** 2026-05-28
**Command:** `.venv/bin/python3 scripts/trade_strategy_classifier.py --apply --limit 55`
**Commit:** bbe3d54
**Model:** gemma3:4b (GPU, Vulkan, Arc B50)

## Summary

| Metric | Value |
|--------|-------|
| Total classified | 55 |
| Errors | 0 |
| Post-validation downgrades | 0 |
| Low confidence (<0.7) | 0 |
| strategy_backtest_trades rows updated | 34 |
| Unique symbols updated | 28 |
| Old strategy_id values | NULL / empty / "unknown" |

## Strategy Distribution

| Strategy | Count | Audit Verdict |
|----------|-------|---------------|
| speculative_growth | 36 | See quality notes below |
| recovery_watch | 6 | 4 questionable (0-day holds) |
| swing_trade | 5 | evidence_supported |
| dividend_growth_compounder | 3 | evidence_supported (ticker+watchlist confirm) |
| sector_rotation | 2 | evidence_supported (ticker+proposal confirm) |
| core_growth_compounder | 2 | questionable (0-day holds) |
| swing_breakout | 1 | evidence_supported |

## Quality Audit — Sampled Reviews

### dividend_growth_compounder (3/3 reviewed)

| Symbol | Account | Conf | Verdict | Notes |
|--------|---------|------|---------|-------|
| APAM | schwab_taxable | 0.8 | evidence_supported | ticker=dividend_growth_compounder, watchlist=income |
| APAM | schwab_rollover_ira | 0.8 | evidence_supported | same enrichment as above |
| PFE | schwab_rollover_ira | 0.85 | evidence_supported | ticker=dividend_growth_compounder, watchlist=income, 244d hold |

All 3 have real dividend/income evidence from both ticker_strategy_classifications AND watchlist_strategy_cards.

### core_growth_compounder (2/2 reviewed)

| Symbol | Account | Conf | Verdict | Notes |
|--------|---------|------|---------|-------|
| AMD | schwab_taxable | 0.85 | **questionable** | ticker=core_growth_compounder but hold_days=0. 0-day hold is not compounder behavior |
| AMD | schwab_rollover_ira | 0.85 | **questionable** | same issue |

AMD is correctly tagged as core_growth_compounder at the ticker level, but a 0-day trade is more consistent with momentum_scalp or swing_trade. The enrichment drove the classification correctly for the *symbol* but not for the *trade*.

### sector_rotation (2/2 reviewed)

| Symbol | Account | Conf | Verdict | Notes |
|--------|---------|------|---------|-------|
| XMTR | schwab_rollover_ira | 0.8 | evidence_supported | ticker=sector_rotation, proposal=swing_breakout with catalyst |
| XMTR | schwab_taxable | 0.8 | evidence_supported | same enrichment |

### recovery_watch (6/6 reviewed)

| Symbol | Account | Conf | Verdict | Notes |
|--------|---------|------|---------|-------|
| BRO | schwab_taxable | 0.8 | evidence_supported | ticker=recovery_watch, 11d hold, negative PnL |
| BRO | schwab_rollover_ira | 0.8 | evidence_supported | same |
| NUWE | schwab_taxable | 0.8 | **questionable** | ticker=recovery_watch but hold_days=0 |
| NUWE | schwab_rollover_ira | 0.8 | **questionable** | same |
| SOPA | schwab_taxable | 0.8 | **questionable** | ticker=recovery_watch but hold_days=0 |
| SOPA | schwab_rollover_ira | 0.8 | **questionable** | same |

NUWE and SOPA: recovery_watch implies holding for recovery. 0-day holds contradict this. The ticker classification reflects the *symbol's general strategy fit*, not the actual trade behavior.

### speculative_growth (10/36 sampled)

| Symbol | Account | Conf | Verdict | Notes |
|--------|---------|------|---------|-------|
| AXTI | schwab_rollover_ira | 0.8 | evidence_supported | ticker+watchlist agree, 148d hold, +518% gain |
| APAM-469 | schwab_rollover_ira | 0.8 | **questionable** | ticker=dividend_growth_compounder but classified speculative_growth. Inconsistent with other APAM trades |
| ADBE | schwab_roth_ira | 0.8 | **needs_manual_review** | ADBE is mega-cap ($200B+), not speculative. watchlist=speculative_growth seems wrong at the source |
| ADBE | schwab_rollover_ira | 0.8 | **needs_manual_review** | same issue |
| GSIT | schwab_taxable | 0.8 | evidence_supported | watchlist=speculative_growth with 8-K catalyst |
| GSIT | schwab_rollover_ira | 0.8 | evidence_supported | same |
| EKSO | schwab_taxable | 0.8 | evidence_supported | watchlist=speculative_growth, FDA catalyst |
| EKSO | schwab_rollover_ira | 0.8 | evidence_supported | same |
| ARKG | schwab_rollover_ira | 0.8 | evidence_supported | ticker+watchlist=speculative_growth (ARK ETF) |
| AGMH | schwab_rollover_ira | 0.8 | evidence_supported | ticker+watchlist=speculative_growth |

## Quality Issue Summary

| Verdict | Count (sampled) | Description |
|---------|----------------|-------------|
| evidence_supported | 17 | Classification backed by enrichment + trade data |
| questionable | 7 | Enrichment correct for symbol but trade behavior contradicts (0-day holds classified as long-term strategies) |
| needs_manual_review | 2 | ADBE: source enrichment (watchlist) may have wrong strategy type |
| likely_wrong | 0 | None clearly wrong given enrichment data |

## Root Cause of Questionable Classifications

The classifier enriches with *symbol-level* strategy data (what strategy this ticker generally belongs to), but does not yet validate whether the *specific trade's behavior* (hold period, PnL pattern) matches that strategy. A 0-day hold on AMD classified as "core_growth_compounder" is technically correct for the symbol but misleading for the trade.

**Fix for next batch:** Add post-validation rule that flags when hold_days conflicts with strategy definition (e.g., core_growth_compounder requires hold > 30 days, recovery_watch requires hold > 5 days).

## Mutation Verification

| Table | Changes in last 2h | From classifier? |
|-------|--------------------|-----------------| 
| strategy_backtest_trades.strategy_id | 34 rows | YES (intended) |
| paper_trades | 6 rows updated | NO (normal pipeline stop management) |
| paper_trade_proposals | 1 row updated | NO (lifecycle check on ATRA) |
| trade_llm_reviews | 0 | N/A |
| trade_journal | 0 | N/A |

No unintended mutations detected.
