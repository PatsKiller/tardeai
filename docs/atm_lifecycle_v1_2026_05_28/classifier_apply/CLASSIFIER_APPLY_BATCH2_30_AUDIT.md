# Classifier Apply Batch 2 — Audit

**Date:** 2026-05-28
**Command:** `.venv/bin/python3 scripts/trade_strategy_classifier.py --apply --limit 30`
**Status:** Completed with Ollama instability; **0 backtest rows updated**

## Key Finding: Batch 2 Is a No-Op

All 55 "unclassified" trades in the `trades` view are the **same symbols** that were already classified in batch 1. The classifier updates `strategy_backtest_trades.strategy_id`, NOT `trade_transactions` or the `trades` view directly.

**Every trade in this batch showed `Updated 0 backtest trade rows`** because:
1. The `trades` view pulls from `trade_transactions` which has no `strategy_id` column updated by the classifier
2. The `strategy_backtest_trades` rows for these symbols were already classified in batch 1
3. The UPDATE query uses `WHERE strategy_id IS NULL OR strategy_id='' OR strategy_id='unknown'` — those rows are already filled

## Remaining Truly Unclassified

| Table | Count | Symbols |
|-------|-------|---------|
| strategy_backtest_trades (NULL strategy_id) | 4 | V, SHFS, FJSCX x2 |
| trades view (no backtest row) | 1 | SGBX |

These 5 are NOT in the current `trades` view query results, so the classifier cannot reach them.

## Ollama Instability

Ollama crashed during the run due to the first attempt being killed (exit 144 / SIGTERM). The SIGTERM corrupted the Ollama runner state, causing `Connection refused` errors for subsequent requests. Ollama auto-restarted via systemd but the batch had already failed on 27/30 trades.

This is a known risk with the current Ollama 0.20.6 on Vulkan — killed inference processes can leave the runner in a bad state.

## Batch Results (Last Complete Run)

| Metric | Value |
|--------|-------|
| Total | 30 |
| Classified (LLM responded) | 3 |
| Errors (Ollama down) | 27 |
| Backtest rows updated | **0** |
| needs_review | 0 |
| Downgrades | 1 (APAM conflict gate) |

## No Rollback Needed

Zero rows were changed in any table. No rollback SQL is necessary.

## Recommendation

1. **Do NOT run batch 2 again** — it will produce the same 0-update result
2. The `trades` view needs to be updated to reflect the classifications from batch 1, OR the classifier needs to update `trade_transactions` directly
3. The 4 remaining backtest trades (V, SHFS, FJSCX) need a separate targeted classification run
4. Consider adding a skip-already-classified check to avoid wasting LLM calls on no-op trades

## Safety Confirmation

| Check | Status |
|-------|--------|
| Backtest rows changed | 0 (no-op) |
| paper_trades changes | NO |
| Proposal/journal mutations | NO |
| Orders placed | NO |
| Broker writes | NO |
| Qwen used | NO |
| Gemma4 used | NO |
| Gemma3 used | YES (3 successful calls before crash) |
| Grok called | NO |
