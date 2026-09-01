# Next Session Runbook — 2026-05-28

Status:      HISTORICAL
as_of:       2026-05-28T23:16:50-04:00
Measured at: efcc51365 / not measured

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

### 1. Classifier Source/Writer Mismatch — FIXED (ae8efe0)

`--apply` now requires `--source strategy_backtest_trades`. The old trades_view path is read-only. 2,567/2,568 rows classified. Only SHFS (id=860) remains — needs enrichment data.

### 2. Reopen Backtesting Lifecycle Phases

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
- Use gemma3:27b on GPU
- Call Grok
- Change ALPACA_MODE or LLM_DISABLE_LIVE_EXECUTION
- Run bulk operations without rollback SQL prepared
- Downgrade from gemma3:12b to gemma3:4b without operator approval
