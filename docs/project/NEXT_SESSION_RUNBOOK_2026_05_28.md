# Next Session Runbook — 2026-05-28

## Pre-Flight (Do First)

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 1. Verify Ollama
ollama --version          # expect 0.24.0
curl -s http://127.0.0.1:11434/api/ps | jq .   # expect gemma3:4b only

# 2. Health check
.venv/bin/python scripts/check_local_llm_health.py   # must PASS 7/7

# 3. Verify model policy
grep -E 'LOCAL_LLM_MODEL|DISABLED_LOCAL_LLM' .env
# expect: gemma3:4b, disabled includes qwen3:14b,gemma4:e2b,gemma4:e4b

# 4. Verify safety
grep -E 'ALPACA_MODE|LLM_DISABLE_LIVE' .env
# expect: paper, true
```

## Recommended Next Steps

### 1. Fix Classifier Source/Writer Mismatch (Priority)

The classifier reads from the `trades` view (trade_transactions) for unclassified rows but writes to `strategy_backtest_trades`. This means:
- The same 55 trades always appear "unclassified" in the trades view
- Batch 2 was a no-op (0 rows updated)
- Running another apply wastes LLM calls

**Options:**
- A) Add a LEFT JOIN exclusion: skip trades whose symbol already has a classified strategy_backtest_trades row
- B) Update trade_transactions.strategy_id after successful backtest classification
- C) Add a `classifier_applied_at` timestamp to track which trades have been processed

### 2. Handle Remaining Unclassified Backtest Trades

3 rows remain (SHFS, FJSCX x2). These need:
- ticker_strategy_classifications entries, OR
- manual classification, OR
- acceptance as needs_review

### 3. Reopen Backtesting Lifecycle Phases

After classifier data is stable:
- Verify strategy distribution makes sense
- Ensure champion simulations are clearly separated from real trades
- Resume backtesting phase work

### 4. Re-Test Gemma4 GPU (After Next Ollama Update Only)

Both Gemma4 models work on CPU but fail on Vulkan. When Ollama releases a new version with Gemma4 Vulkan support:
```bash
ollama pull gemma4:e2b
.venv/bin/python scripts/canary_local_llm_models.py  # CPU canary
# then manually test GPU with num_gpu=-1
```

## Do NOT

- Run classifier --apply without health check and pre-state export
- Update Ollama without explicit approval
- Enable qwen3:14b or gemma4 for production
- Change ALPACA_MODE or LLM_DISABLE_LIVE_EXECUTION
- Run bulk operations without rollback SQL prepared
