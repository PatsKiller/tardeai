# v4.0 Recurring Backtest + LLM Coverage Implementation Report

**Date:** 2026-05-28

## What Was Implemented

### A. Schema Migration
- `trade_llm_reviews.backtest_trade_id` BIGINT column added
- `trade_llm_reviews.source_table` TEXT column added (default: 'paper_trades')
- Indexes: `idx_tlr_backtest`, `idx_tlr_source`
- SQL: `sql/llm_backtest_coverage_v4_0.sql`

### B. LLM Analyzer Extension (trade_close_llm_analyzer.py v4.0)
- New `--source backtest|paper` flag (default: paper)
- New `--backtest-trade-id` flag for single-trade lookup
- Batch mode: `--source backtest --limit 50` processes up to 50 unreviewed backtest trades
- Unreviewed detection: LEFT JOIN against trade_llm_reviews to skip already-reviewed trades
- `_build_backtest_input()` — builds snapshots from strategy_backtest_trades
- `_write_review_row()` — writes trade_llm_reviews with source_table and backtest_trade_id
- Backward compatible: `--source paper` behaves identically to v3.8

### C. Recurring Cron Entries (3 new jobs)
| Job | Schedule | Command |
|-----|----------|---------|
| Enterprise Backtester | Sunday 10 PM ET | `enterprise_backtester.py --replay-trades --apply` |
| Strategy Backtester (Daily) | Weekdays 6 AM ET | `strategy_backtester.py --all-strategies --apply` |
| LLM Backtest Trade Reviewer | Sunday 11 PM ET | `trade_close_llm_analyzer.py --source backtest --limit 50 --apply --confirm-llm-review-write --allow-local-llm` |

All guarded by `safe_flock.sh` to prevent overlap.

### D. Health Agent Registration (3 new components)
| Component | Display | Max Age | Critical |
|-----------|---------|---------|----------|
| enterprise_backtester | Enterprise Backtester | 10080 min (1 week) | No |
| strategy_backtester | Strategy Backtester (Daily) | 1500 min (~25 hrs) | No |
| llm_backtest_reviewer | LLM Backtest Trade Reviewer | 10080 min (1 week) | No |

### E. API Enhancement
- `/api/v2/lifecycle/llm-review-status` now includes `coverage` object:
  - `paper_trades.reviewed`, `paper_trades.closed_total`, `paper_trades.unreviewed`
  - `backtest_trades.reviewed`, `backtest_trades.total`, `backtest_trades.unreviewed`
- `/api/v2/lifecycle/trade-llm-review` now supports `?backtest_trade_id=` and `?source=` filters

## Coverage Status (As of Implementation)
| Source | Reviewed | Total | Unreviewed |
|--------|----------|-------|------------|
| paper_trades | 4 | 30 closed | 26 |
| strategy_backtest_trades | 0 | 872 | 872 |

At 50 trades/week, full backtest coverage in ~18 weeks (Sunday batch runs).

## Dry-Run Validation
```
$ python trade_close_llm_analyzer.py --source backtest --limit 3
Processing 3 backtest trade(s)
Trade: RLYB #1 source=backtest hash=6d96ecd63bbbcd11
Trade: FTCI #2 source=backtest hash=d054589ccf847e54
Trade: CELU #3 source=backtest hash=62c91b30aabd899d
```

Paper source backward compat verified: APPS #34 returns same hash (504b60ef).

## Safety
- No orders placed / No broker writes / No paper_trades changes
- No proposal/journal/backtest mutations
- ALPACA_MODE=paper, LLM_DISABLE=true
- Backtest crons write to strategy_backtest_trades only
- LLM cron writes to trade_llm_reviews only (read-only for trade data)
- All crons safe_flock guarded

## Rollback
```sql
-- Schema
ALTER TABLE trade_llm_reviews DROP COLUMN IF EXISTS backtest_trade_id;
ALTER TABLE trade_llm_reviews DROP COLUMN IF EXISTS source_table;
DROP INDEX IF EXISTS idx_tlr_backtest;
DROP INDEX IF EXISTS idx_tlr_source;
```
```bash
# Cron — remove v4.0 section from crontab
crontab -l | sed '/v4.0 Recurring Backtest/,/llm_backtest_review/d' | crontab -
```

## Files Changed
- `sql/llm_backtest_coverage_v4_0.sql` (new)
- `scripts/trade_close_llm_analyzer.py` (v3.8 -> v4.0)
- `scripts/system_health_agent.py` (+3 components)
- `scripts/api_v2.py` (llm-review-status coverage, trade-llm-review backtest support)
- Crontab (+3 entries)
