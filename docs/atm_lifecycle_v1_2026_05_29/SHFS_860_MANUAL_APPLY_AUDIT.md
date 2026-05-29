# SHFS id=860 Manual Apply Audit — 2026-05-29

## Operator Approval
> "Apply SHFS 860 as speculative_growth — I approve Option A direct SQL."
— John, 2026-05-29

## Pre-State
| Field | Value |
|-------|-------|
| id | 860 |
| symbol | SHFS |
| strategy_id | (empty string) |
| Classification | 3,592 / 3,593 (99.97%) |

## SQL Executed
```sql
UPDATE strategy_backtest_trades
SET strategy_id = 'speculative_growth'
WHERE id = 860
  AND symbol = 'SHFS'
  AND (strategy_id IS NULL OR strategy_id = '');
```

## Rows Updated
**1** (exactly one)

## Post-State
| Field | Value |
|-------|-------|
| id | 860 |
| symbol | SHFS |
| strategy_id | speculative_growth |
| Classification | **3,593 / 3,593 (100%)** |
| Unclassified remaining | **0** |

## Reason for Manual Classification
1. gemma3:12b dry-run correctly returned `needs_review` (confidence 0.3) due to zero enrichment data
2. 9/9 comparable peers in same ER run (ER_20260521121822_32aeb8) — all sub-$10 micro-cap, 1-day hold, stop_hit, -5% — were classified as `speculative_growth`
3. SHFS (SHF Holdings Inc Class A, cannabis banking/fintech micro-cap, $6.78) matches this pattern exactly
4. No direct enrichment data exists (no proposals, paper_trades, watchlist, ticker classifications, market data, or news)
5. Operator reviewed peer comparison and approved Option A direct SQL

## Rollback Path
```sql
UPDATE strategy_backtest_trades
SET strategy_id = NULL
WHERE id = 860
  AND symbol = 'SHFS'
  AND strategy_id = 'speculative_growth';
```
File: `docs/atm_lifecycle_v1_2026_05_29/shfs_860_apply/SHFS_860_ROLLBACK.sql`

## Safety Confirmation
| Check | Result |
|-------|--------|
| Orders placed | **NO** |
| Broker writes | **NO** |
| paper_trades changes | **NO** |
| Proposal mutations | **NO** |
| Journal mutations | **NO** |
| Classifier --apply run | **NO** |
| LLM calls | **NO** |
| Qwen/Gemma4/Grok used | **NO** |
| Cron changes | **NO** |
| .env changes | **NO** |
| DB writes | **Exactly 1 row** (strategy_backtest_trades id=860) |
