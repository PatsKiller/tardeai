# Next Session Runbook — 2026-05-29

Status:      HISTORICAL
as_of:       2026-05-29T10:03:57-04:00
Measured at: efcc51365 / not measured

## Pre-Flight

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# 1. Health check
.venv/bin/python scripts/check_local_llm_health.py   # must PASS 7/7

# 2. Verify Ollama
ollama --version          # expect 0.24.0
curl -s http://127.0.0.1:11434/api/ps | jq .

# 3. Verify model policy
grep -E 'LOCAL_LLM_MODEL|DISABLED_LOCAL_LLM' .env

# 4. Verify safety
grep -E 'ALPACA_MODE|LLM_DISABLE_LIVE' .env

# 5. Verify classifier state
.venv/bin/python3 -c "
import sys; sys.path.insert(0, 'scripts')
from db_adapter import _get_conn
conn = _get_conn(); cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM strategy_backtest_trades WHERE strategy_id IS NULL OR strategy_id = '' OR strategy_id = 'unknown'\")
print(f'Unclassified: {cur.fetchone()[0]}')  # expect 1 (SHFS)
conn.close()
"
```

## Recommended Next Steps

### 1. SHFS (id=860) Manual Classification

Only unclassified backtest trade. Options:
- Add enrichment data (ticker_strategy_classifications entry) then re-run classifier
- Manual classification if strategy is known
- Accept as needs_review permanently

### 2. Trade Close Analyzer Batch (Operator Approval Needed)

Run gemma3:12b close-trade analysis on unreviewed backtest trades:
```bash
.venv/bin/python scripts/trade_close_llm_analyzer.py --dry-run --allow-local-llm \
  --source backtest --limit 10 --model-name gemma3:12b --prompt-version close_analysis_v2
```

### 3. Gemma4 31B Overnight Deep Review (Optional)

If operator approves, create systemd service for llama-server and run deep analysis:
```bash
cd ~/llama-cpp-vulkan/llama-b9405
LD_LIBRARY_PATH=$(pwd) ./llama-server \
  --model ~/llama-cpp-vulkan/gemma4-31b-hf.gguf \
  --port 8081 --ctx-size 2048 --n-gpu-layers 25 --threads 6
```
Note: Must unload Ollama models first to free VRAM.

### 4. llama.cpp Production Evaluation (If Pursuing)

Requirements before switching from Ollama:
- systemd service with auto-restart
- VRAM contention guard with embedding models
- 50+ trade classifier dry-run batch
- Health check integration
- Clear rollback path to Ollama

## Do NOT

- Run bulk classifier apply (phase complete)
- Use legacy trades_view apply path
- Enable qwen3:14b, gemma4, or gemma3:27b on GPU
- Call Grok
- Update Ollama without approval
- Switch to llama.cpp production without 50+ trade validation
- Change ALPACA_MODE or LLM_DISABLE_LIVE_EXECUTION
