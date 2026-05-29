# Session 2026-05-29 — Trade AI Classifier Completion & llama.cpp Canary

**Commits:** 5 (7045209 through 9364ff1)

## Executive Summary

Completed the classifier/backtesting integrity phase and ran the first llama.cpp Vulkan canary. Fixed 13 hardcoded qwen3:14b references across runtime scripts, validated the source/writer alignment fix, confirmed 3,592/3,593 backtest trades classified, and benchmarked llama.cpp b9405 against Ollama 0.24.0 on gemma3:12b.

## Commits

| Hash | Description |
|------|-------------|
| `7045209` | Fix trade close analyzer num_ctx for gemma3:12b GPU mode |
| `40c1ae1` | Fix hardcoded qwen3:14b warmup in GPU lifecycle and overnight scripts |
| `b6e7571` | Replace hardcoded qwen3:14b with env-driven model across 10 runtime scripts |
| `71bc6bc` | Validate classifier source/writer fix and backtesting lifecycle |
| `9364ff1` | llama.cpp Vulkan canary: 2/3 PASS, 2-9x faster than Ollama |

## Work Completed

### 1. Hardcoded Model Reference Cleanup (40c1ae1, b6e7571)

13 runtime files fixed. All hardcoded `qwen3:14b` references replaced with `os.getenv("LOCAL_LLM_MODEL", "gemma3:4b")` or updated constants:

- `api_v2.py` — 10 agent identities
- `run_deep_overnight_llm_window.sh` — RESTORE_MODEL
- `run_batch_overnight_gemma_pilot.sh` — RESTORE_MODEL + emergency warmup
- `health_agent_llm_review.py`, `multi_tier_trade_reviewer.py`, `claude_escalation_handler.py` — Ollama call payloads
- `report_llm_fleet_status.py`, `write_daily_llm_fleet_summary.py` — fleet reports
- `phase3_media_prose_routing_policy.py`, `prefetch_hybrid_rag_context.py` — policy/RAG
- `run_phase2c_hybrid_offline_pilot.sh`, `run_phase3d_expanded_media_prose_pilot.py` — pilot scripts
- `gpu_lifecycle.py` — docstring examples

**Root cause of "GPU lifecycle warmup failed for qwen3:14b" alert:** Overnight scripts had `RESTORE_MODEL="qwen3:14b"` — tried to warmup a disabled model after every batch.

### 2. Trade Close Analyzer Fix (7045209)

Added `num_ctx=4096` for gemma3:12b in `_call_ollama_direct()`. Without this, gemma3:12b's default 131K context caused HTTP 500 on VRAM overcommit. Dry-run result: 2/3 meaningful_structured_review.

### 3. Classifier/Backtesting Validation (71bc6bc)

- Source/writer fix confirmed working (commit ae8efe0 from yesterday)
- 3,592/3,593 backtest trades classified (99.97%)
- Only SHFS (id=860) remains — no enrichment data
- Champion simulations (BT_*, 3,516) clearly separated from replays (ER_*, 77)
- trade_transactions 153 unclassified is expected (no strategy_id column)

### 4. llama.cpp Vulkan Canary (9364ff1)

Built and tested llama.cpp b9405 (pre-built Ubuntu Vulkan x64) against Ollama 0.24.0:

| Test | llama.cpp | Ollama | Speedup |
|------|----------|--------|---------|
| basic_json | **2.8s** | 26.6s | 9.5x |
| strategy_classifier | **9.1s** | 11.1s | 1.2x |
| close_trade_analysis | 19.0s | 31.3s | 1.6x |

**Key finding:** Ollama's GGUF format is incompatible with upstream llama.cpp — separate model downloads required from HuggingFace.

**Recommendation:** Keep as benchmark tool. Production switch requires systemd service, VRAM contention handling, and 50+ trade batch validation.

## Model Policy (Unchanged)

- Primary: gemma3:12b on GPU/Vulkan
- Fallback: gemma3:4b
- Disabled: qwen3:14b, gemma4:e2b, gemma4:e4b, gemma3:27b on GPU

## Safety Confirmation

| Check | Status |
|-------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Orders placed | NONE |
| Broker writes | NONE |
| Cron changes | NONE |
| .env changes | NONE |
| DB writes | NONE (today) |
| Ollama updated | NO |
| llama-server | Stopped after canary |
| Health check | PASS (7/7) |

## Next Steps

1. Consider systemd service for llama-server if pursuing as production alternative
2. SHFS (id=860) needs enrichment data for classification
3. Trade close analyzer batch with gemma3:12b (pending operator approval)
4. No more classifier batches needed — phase complete
