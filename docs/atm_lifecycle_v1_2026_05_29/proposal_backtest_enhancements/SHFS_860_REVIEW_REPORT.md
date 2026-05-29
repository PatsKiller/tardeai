# SHFS id=860 Review Report — 2026-05-29

## Evidence Available
- **Trade data**: Buy 2025-09-24 @6.78, Sell 2025-09-25 @6.57 (stop_hit, -5%, R=-1.0)
- **Backtest context**: ER (Earnings Run) replay, run_id ER_20260521121822_32aeb8
- **MFE/MAE**: MFE 5.6%, MAE -13.27% — saw upside but hit stop
- **Symbol**: SHF Holdings Inc Class A — cannabis banking/fintech micro-cap (~$6-7 range)
- **Holding period**: 1 day
- **Account**: schwab_rollover_ira

## Evidence Missing
- No ticker_strategy_classifications row
- No watchlist_strategy_cards row
- No paper_trade_proposals row
- No market OHLCV bars
- No news articles
- No screener membership
- No enrichment data of any kind

## Peer Comparison (same ER run)
Nearly all similar trades in the same ER run (small-cap, sub-$10, stop_hit, negative PnL) were classified as **speculative_growth**:
- DFSC, PHIO, FUSE, TRX, SHPH, BNAI, MSGM, IBIO — all speculative_growth
- Exceptions: momentum_scalp (GCTS @$1.49), swing_trade (FATN), recovery_watch (NUWE)

## Proposed Classification
- **Strategy**: `speculative_growth`
- **Confidence**: ~0.3-0.4 (low, due to zero enrichment)
- **Reason**: Cannabis micro-cap, 1-day earnings hold, stop_hit — pattern matches speculative_growth peers in same run
- **Classifier behavior**: Would flag `requires_review = true` due to no enrichment context

## Dry-Run Feasibility
**FEASIBLE** — enough trade context exists for a dry-run classification.

```bash
.venv/bin/python scripts/trade_strategy_classifier.py \
  --dry-run \
  --symbols SHFS \
  --source strategy_backtest_trades \
  --limit 1 \
  --model gemma3:12b \
  --json-out logs/strategy_classifier_shfs_860_dry_run.json
```

**NOT RUN** — requires operator approval before execution. The dry-run will not write to DB but will call gemma3:12b.

## Apply Safety
- **Safe to dry-run**: Yes (read-only, no DB mutation)
- **Safe to apply without review**: No (zero enrichment = requires_review)
- **Recommendation**: Run dry-run, review output, then operator approves or rejects

## Rollback SQL (if apply is later approved)
```sql
-- Pre-state: strategy_id IS NULL for id=860
-- Rollback:
UPDATE strategy_backtest_trades
SET strategy_id = NULL
WHERE id = 860;
```

## Decision
**DO NOT APPLY** without operator approval. Dry-run is recommended but not executed in this session.
Manual enrichment checklist if operator wants to enrich before classification:
1. Add SHFS to ticker_strategy_classifications with appropriate strategy
2. Or: run classifier with --dry-run and review LLM output
3. Or: manually set strategy_id = 'speculative_growth' with rollback SQL ready
