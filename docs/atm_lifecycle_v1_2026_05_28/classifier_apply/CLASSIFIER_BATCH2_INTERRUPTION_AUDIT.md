# Classifier Batch2 Interruption Audit

**Date:** 2026-05-28

## Timeline

1. Batch2 started: `--apply --limit 30`
2. First run killed by timeout (exit 144 / SIGTERM) after ~25 trades
3. SIGTERM corrupted Ollama runner state → Connection refused
4. Second run: 7/30 classified before Ollama crashed again (Connection refused)
5. Third run: 3/30 classified before Ollama went down
6. Operator upgraded Ollama from 0.20.6 to 0.24.0
7. Ollama restarted, health check PASS

## Batch2 Final Output Analysis

**File:** `logs/strategy_classifier_apply_batch2_30.json`

| Metric | Value |
|--------|-------|
| JSON valid | YES |
| Total trades | 30 |
| Classified (LLM responded) | 3 |
| Errors (Connection refused) | 27 |
| **Backtest rows updated** | **0** |
| needs_review | 0 |
| unknown | 0 |
| Post-validation downgrades | 1 (APAM conflict gate) |
| Duplicate trade_ids | **NONE** |

## Why 0 Rows Updated

All 30 trades are the same symbols already classified in batch 1. The classifier queries the `trades` view (from `trade_transactions`) for unclassified rows, but writes to `strategy_backtest_trades`. Since batch 1 already set `strategy_id` on all reachable `strategy_backtest_trades` rows, the UPDATE query's WHERE clause (`strategy_id IS NULL OR strategy_id='' OR strategy_id='unknown'`) matches 0 rows.

**Batch2 is a confirmed no-op for DB writes.**

## Interruption Impact

| Check | Result |
|-------|--------|
| Partially written rows | NONE (0 updates) |
| Corrupt rows | NONE |
| Duplicate classifications | NONE |
| Qwen called | NO (safety log confirms gemma3:4b only) |
| Gemma4 called | NO |
| Grok called | NO |
| Model errors during restart | YES — Connection refused after SIGTERM |

## Safety Log Verification

`logs/llm_router_safety.jsonl` shows only `gemma3:4b` calls with `resolved_model=gemma3:4b` and `disabled_model_blocked=false`. No qwen or gemma4 entries during batch2.

## Mutation Verification

| Table | Changes last 3h | From classifier? |
|-------|-----------------|-------------------|
| strategy_backtest_trades | 0 new updates | N/A |
| paper_trades | 6 updated | NO (normal pipeline) |
| paper_trade_proposals | 2 updated | NO (lifecycle checks) |
| trade_llm_reviews | 0 created | N/A |

**No unintended mutations.**

## Remaining Unclassified

| Location | Count | Symbols |
|----------|-------|---------|
| strategy_backtest_trades (NULL strategy_id) | 4 | V, SHFS, FJSCX x2 |
| trades view (no backtest row) | 1 | SGBX |

These 5 are not reachable by the current classifier query.

## Rollback

**Not needed.** 0 rows changed. Rollback SQL exists for audit completeness at:
`classifier_apply/classifier_batch2_interruption_rollback.sql`

## Recommendation

1. **Do NOT re-run batch2** — it will produce the same 0-update result
2. The 4 remaining backtest trades (V, SHFS, FJSCX) can be classified with a targeted query if needed
3. Classifier is complete for all trade_transactions-sourced trades
4. Next classifier work: update the `trades` view or `trade_transactions` to reflect batch1 classifications, OR close the classifier phase as complete
