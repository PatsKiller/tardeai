# Ollama 0.24.0 Upgrade and Model Canary Report

**Date:** 2026-05-28
**Operator action:** Manual upgrade via `curl -fsSL https://ollama.com/install.sh | sh`

## Version

| Item | Value |
|------|-------|
| Version before | 0.20.6 |
| Version after | **0.24.0** |
| Latest stable | v0.24.0 (current) |

## Service Environment After Upgrade

Safety override remains active (systemd drop-in `/etc/systemd/system/ollama.service.d/99-tradeai-llm-safety.conf`):

- `OLLAMA_KEEP_ALIVE=5m`
- `OLLAMA_NUM_PARALLEL=1`
- `OLLAMA_MAX_LOADED_MODELS=1`
- `OLLAMA_VULKAN=1`
- `OLLAMA_NUM_GPU=-1`

Keep-alive timestamps are now normal (no more year-2318 far-future expiration).

## Model Canary Results

| Model | Status | Detail |
|-------|--------|--------|
| gemma3:4b | **PASS** | Valid JSON output, numeric test returned "4", structured JSON test returned `{"answer":4,"status":"ok"}` |
| gemma4:e2b | **FAIL** | Failed to load after upgrade |
| qwen3:14b | **FAIL** | Returned empty content with thinking only, no usable output |

## Production Model Decision

**Keep gemma3:4b as production model.** No change. Both alternative models failed canary.

## Disabled Model Decision

All remain disabled in `DISABLED_LOCAL_LLM_MODELS`:
- `qwen3:14b` — empty content, thinking only, VRAM overcommit risk
- `gemma4:e2b` — fails to load
- `gemma4:e4b` — untested, kept disabled as precaution

## Health Check After Upgrade

```
PASS (7/7)
- ollama_reachable: PASS
- qwen3_not_loaded: PASS
- gemma3_numeric: PASS
- gemma3_json: PASS
- disabled_model_routing: PASS
- max_one_model: PASS
- no_unsafe_jobs: PASS
```

## Final Loaded Models

- gemma3:4b (7.2 GiB VRAM, Q4_K_M, Vulkan)
- No other models loaded

## Upgrade Notes

- v0.24.0 includes improved Vulkan backend stability and memory management
- GPU layer detection now shows 35 layers offloaded (was 41 on v0.20.6 — Ollama auto-selects based on VRAM headroom)
- KV cache: 2.7 GiB, compute graph: 403 MiB, total: 6.7 GiB
- Model load time: ~2.3s (cold start)

## Safety Confirmation

| Check | Status |
|-------|--------|
| Production model | gemma3:4b (unchanged) |
| Qwen loaded | NO |
| Gemma4 loaded | NO |
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Orders placed | NO |
| Broker writes | NO |
