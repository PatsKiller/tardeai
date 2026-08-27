# Local LLM Model Final Decision After Canary

**Date:** 2026-05-28
**Ollama:** 0.24.0

## Decision

**Production model: gemma3:4b on GPU (Vulkan, Arc B50)**

No model change. gemma3:4b remains the only model authorized for production routing.

## Canary Results Summary

| Model | CPU Workload | GPU Workload | Decision |
|-------|-------------|-------------|----------|
| gemma3:4b | 3/3 PASS | 3/3 PASS (production) | **Keep as production** |
| gemma4:e4b | 3/3 PASS (58-75s) | 0/3 FAIL (garbage output) | Removed |
| gemma4:e2b | 3/3 PASS (45s) | 0/3 FAIL (HTTP 500) | Removed |
| qwen3:14b | 1/3 PASS (84s) | N/A (VRAM overcommit) | Disabled |

## Models Removed

- `gemma4:e2b` — removed from Ollama (already cleaned during 0.24.0 upgrade)
- `gemma4:e4b` — removed from Ollama (already cleaned during 0.24.0 upgrade)

Both Gemma4 models produce valid structured JSON on CPU but fail completely on Vulkan GPU. Until Ollama adds proper Gemma4 Vulkan support, they cannot be used in production.

## Models Retained (Installed)

| Model | Size | Purpose |
|-------|------|---------|
| gemma3:4b | 3.3 GB | Production classifier/analyzer |
| qwen3:14b | 9.3 GB | Disabled, kept for future re-test |
| gemma3:27b | 17 GB | Large model, not used in pipeline |
| gemma3-overnight | 17 GB | Overnight batch pilot (inactive) |
| nomic-embed-text | 274 MB | Embedding model |
| qwen3-embedding:8b | 4.7 GB | Embedding model |

## Models Disabled in Router

`DISABLED_LOCAL_LLM_MODELS=qwen3:14b,gemma4:e2b,gemma4:e4b`

Even though gemma4 models are removed from Ollama, they remain in the disabled list as a safety net — if someone reinstalls them, the router will still block them.

## Qwen5

Not available or validated for this system. No Qwen5 model was tested or used.

## Production Configuration

| Setting | Value |
|---------|-------|
| LOCAL_LLM_MODEL | gemma3:4b |
| LOCAL_LLM_SAFE_MODEL | gemma3:4b |
| DISABLED_LOCAL_LLM_MODELS | qwen3:14b,gemma4:e2b,gemma4:e4b |
| LOCAL_LLM_MAX_CONCURRENT | 1 |
| OLLAMA_KEEP_ALIVE | 5m |
| OLLAMA_MAX_LOADED_MODELS | 1 |
| Ollama version | 0.24.0 |

## Safety Confirmation

| Check | Status |
|-------|--------|
| DB writes | NONE |
| Orders placed | NONE |
| Broker writes | NONE |
| Cron changes | NONE |
| .env modified | NO |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Health check | PASS (7/7) |
| Loaded models | gemma3:4b only |
