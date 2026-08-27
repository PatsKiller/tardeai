# SHFS id=860 Operator Approval Apply Plan — 2026-05-29

## DO NOT EXECUTE WITHOUT OPERATOR APPROVAL

## What Would Be Updated
| Field | Current | Proposed |
|-------|---------|----------|
| Table | strategy_backtest_trades | — |
| Row ID | 860 | — |
| strategy_id | NULL | speculative_growth |

No other fields would change.

## Proposed Classification
- **Strategy**: speculative_growth
- **Confidence**: 0.5 (capped — no direct enrichment evidence)
- **Reasoning**: Cannabis/fintech micro-cap ($6.78), 1-day earnings hold, stop_hit at -5%, R=-1.0. Pattern matches 9/9 comparable peers in same ER run (BNAI, GXAI, IBIO, PHIO, SHPH, DFSC, TRX, MSGM, FUSE) all classified as speculative_growth.
- **Evidence**: Peer comparison from ER run ER_20260521121822_32aeb8. No direct enrichment data available.

## Option A: Manual Direct Apply (simplest)
```sql
-- Pre-state verification:
SELECT id, symbol, strategy_id FROM strategy_backtest_trades WHERE id = 860;
-- Expected: id=860, symbol=SHFS, strategy_id=NULL

-- Apply:
UPDATE strategy_backtest_trades
SET strategy_id = 'speculative_growth'
WHERE id = 860 AND symbol = 'SHFS' AND (strategy_id IS NULL OR strategy_id = '');

-- Post-state verification:
SELECT id, symbol, strategy_id FROM strategy_backtest_trades WHERE id = 860;
-- Expected: id=860, symbol=SHFS, strategy_id='speculative_growth'
```

## Option B: Enrichment-First Then Classifier
```sql
-- Step 1: Add ticker classification
INSERT INTO ticker_strategy_classifications (symbol, strategy_id, confidence, source, created_at)
VALUES ('SHFS', 'speculative_growth', 0.5, 'manual_peer_comparison', NOW());

-- Step 2: Re-run classifier
.venv/bin/python scripts/trade_strategy_classifier.py \
  --dry-run \
  --source strategy_backtest_trades \
  --symbols SHFS \
  --model gemma3:12b

-- Step 3: If classifier agrees, apply
.venv/bin/python scripts/trade_strategy_classifier.py \
  --apply \
  --source strategy_backtest_trades \
  --symbols SHFS \
  --model gemma3:12b
```

## Rollback SQL
```sql
-- Rollback Option A:
UPDATE strategy_backtest_trades
SET strategy_id = NULL
WHERE id = 860 AND symbol = 'SHFS';

-- Rollback Option B (also remove ticker classification):
UPDATE strategy_backtest_trades
SET strategy_id = NULL
WHERE id = 860 AND symbol = 'SHFS';

DELETE FROM ticker_strategy_classifications
WHERE symbol = 'SHFS' AND source = 'manual_peer_comparison';
```

## Post-Apply Verification
```sql
-- Classification completeness:
SELECT COUNT(*) as total,
       COUNT(*) FILTER (WHERE strategy_id IS NOT NULL AND strategy_id != '' AND strategy_id != 'unknown') as classified
FROM strategy_backtest_trades;
-- Expected after apply: 3593 total, 3593 classified (100%)
```

## Impact
- Completes backtest classification: 3,592/3,593 → 3,593/3,593 (100%)
- No impact on automated trading (backtest labels are advisory only)
- No impact on journal (journal reads from paper_trades/trade_closed, not strategy_backtest_trades)
- No orders placed
- No broker interaction
