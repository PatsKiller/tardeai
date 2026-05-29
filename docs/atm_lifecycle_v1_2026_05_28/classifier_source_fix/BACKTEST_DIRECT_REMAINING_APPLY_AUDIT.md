# Backtest Direct Remaining Symbols — Apply Audit

**Date:** 2026-05-28
**Model:** gemma3:12b (GPU/Vulkan)
**Source:** --source strategy_backtest_trades --symbols SHFS,FJSCX

## Results

| ID | Symbol | Strategy | Confidence | Evidence | DB Updated | Notes |
|----|--------|----------|------------|----------|------------|-------|
| 860 | SHFS | needs_review | 0.3 | None | Skipped | No enrichment data |
| 874 | FJSCX | speculative_growth | 0.5 | watchlist=core_holding | 1 row | Conflict flagged, requires_review=true |
| 875 | FJSCX | speculative_growth | 0.5 | watchlist=core_holding | 1 row | Conflict flagged, requires_review=true |

## Summary

- **2 rows updated** (FJSCX id=874, id=875)
- **1 row skipped** (SHFS id=860 — needs_review, no enrichment)
- **Remaining unclassified:** 1 (SHFS id=860)
- Old values: NULL for all 3
- New values: speculative_growth for FJSCX, unchanged for SHFS

## Quality Notes

FJSCX classifications are tentative (confidence=0.5, conflict flagged). The only enrichment source is `watchlist_strategy=core_holding`, which conflicts with the LLM's `speculative_growth` classification. Both rows have `requires_review=true`.

SHFS correctly returned `needs_review` — zero enrichment data means no classification is possible.

## Rollback

```bash
psql -U trade_ai -d trade_ai < docs/atm_lifecycle_v1_2026_05_28/classifier_source_fix/backtest_direct_remaining_rollback.sql
```

## Safety

| Check | Status |
|-------|--------|
| Source/writer aligned | YES (strategy_backtest_trades → strategy_backtest_trades) |
| trade_transactions changed | NO |
| paper_trades changed | NO |
| Proposals/journal changed | NO |
| Orders placed | NO |
| Broker writes | NO |
| Model used | gemma3:12b |
| Qwen used | NO |
| Gemma4 used | NO |
| Grok called | NO |
