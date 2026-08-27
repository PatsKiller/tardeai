# Candidate Model Workload Canary Report

**Date:** 2026-05-28
**Mode:** CPU-only (num_gpu=0, num_ctx=2048, temperature=0, seed=1)
**Timeout:** 120s per test

## Results Summary

| Model | basic_json | strategy_classifier | close_trade_analysis | Score |
|-------|-----------|--------------------|--------------------|-------|
| **gemma4:e4b** | PASS (4.7s) | PASS (58.3s) | PASS (74.9s) | **3/3** |
| **gemma4:e2b** | PASS (12.2s) | PASS (45.2s) | PASS (45.3s) | **3/3** |
| qwen3:14b | PASS (84.7s) | FAIL (timeout) | FAIL (timeout) | 1/3 |

## Detailed Results

### gemma4:e4b (3/3 PASS)

- **basic_json:** 4.7s, 10 tokens. Returned exact `{"answer":4,"status":"ok"}`.
- **strategy_classifier:** 58.3s, 699 tokens. Returned valid structured JSON with strategy_id, confidence, reasoning, evidence_used, missing_evidence, requires_review.
- **close_trade_analysis:** 74.9s, 944 tokens. Returned valid structured JSON with summary, thesis_assessment, execution_assessment, stop_assessment, lessons, confidence.

### gemma4:e2b (3/3 PASS)

- **basic_json:** 12.2s, 116 tokens. Valid JSON (verbose but correct).
- **strategy_classifier:** 45.2s, 704 tokens. Valid structured classification.
- **close_trade_analysis:** 45.3s, 974 tokens. Valid structured analysis.

gemma4:e2b is faster than e4b on classifier and analysis prompts (45s vs 58-75s).

### qwen3:14b (1/3 PASS)

- **basic_json:** 84.7s, 344 tokens. Valid JSON but extremely slow.
- **strategy_classifier:** FAIL — timeout at 120s, 0 tokens returned.
- **close_trade_analysis:** FAIL — timeout at 120s, 0 tokens returned.

Qwen3:14b is too slow on CPU for real workloads. The 14B parameter count makes CPU inference impractical at 120s timeout.

## Best Candidate

**gemma4:e2b** — 3/3 passed, fastest on workload prompts (45s), good token output.

**gemma4:e4b** — 3/3 passed, slightly slower (58-75s), slightly fewer tokens on basic_json (more concise).

Both Gemma4 models produce valid structured JSON for both classifier and close-trade-analysis workloads on CPU.

## Can Any Model Replace gemma3:4b?

**Not yet for production.** While both Gemma4 models pass CPU workload canaries:

1. **GPU mode is required for production** — CPU times (45-75s per call) are too slow for batch classification (55 trades = 40-70 minutes on CPU vs ~5 minutes on GPU)
2. **Gemma4 GPU mode failed in prior canary** — gemma4:e2b wouldn't load, gemma4:e4b returned bad content on Vulkan
3. **gemma3:4b GPU mode works** — ~3-12s per call, proven stable over 55-trade apply

## CPU vs GPU Safety

| Model | CPU | GPU (Vulkan) |
|-------|-----|-------------|
| gemma3:4b | PASS (slow) | PASS (fast, production) |
| gemma4:e4b | PASS (58-75s) | FAIL (bad content) |
| gemma4:e2b | PASS (45s) | FAIL (won't load) |
| qwen3:14b | PARTIAL (too slow) | FAIL (VRAM overcommit) |

## Recommendation

1. **Production default remains gemma3:4b on GPU.** No change.
2. **Gemma4 remains GPU-disabled.** Both models fail on Vulkan. Re-test after next Ollama update.
3. **Qwen remains production-disabled.** Too slow on CPU, fails on GPU.
4. **gemma4:e2b is the top CPU fallback candidate** if a CPU-only pipeline is needed (e.g., overnight batch with GPU reserved for other work).
5. **Next step:** When Ollama adds better Gemma4 Vulkan support, re-test GPU mode. If gemma4:e2b passes GPU canary, it could replace gemma3:4b for classifier workloads.

## No Production Changes Made

- .env: NOT modified
- Disabled models list: NOT changed
- Production router: NOT modified
- DB writes: NONE
- All candidate models unloaded after testing
- Final loaded models: gemma3:4b only (reloaded by production health check)
