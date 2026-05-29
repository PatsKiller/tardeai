# Gemma4 31B llama.cpp Vulkan Canary Report

**Date:** 2026-05-29
**Model:** gemma-4-31B-it Q3_K_M (14 GB, from unsloth/gemma-4-31B-it-GGUF)
**Engine:** llama.cpp b9405 (pre-built Ubuntu Vulkan x64)
**GPU:** Intel Arc Pro B50 (BMG G21), 16 GB VRAM
**Config:** 25 GPU layers + CPU offload, ctx=2048, threads=6

## Results

| Test | Status | Latency | Tokens | Notes |
|------|--------|---------|--------|-------|
| basic_json | **PASS** | 42.6s | 113 | Correct `{"answer":4,"status":"ok"}` |
| strategy_classifier | **PASS** | 236.9s | 623 | Correct strategy_id=speculative_growth, confidence=0.9, rich reasoning |
| close_trade_analysis | **PASS** | 279.0s | 721 | Meaningful summary, thesis/execution/stop assessments, lessons |

**Score: 3/3 PASS**

## Comparison with Other Models

| Model | Engine | basic_json | classifier | close_trade | GPU layers |
|-------|--------|-----------|-----------|-------------|------------|
| **gemma4:31B Q3** | llama.cpp | 42.6s | 236.9s | 279.0s | 25 (hybrid) |
| gemma3:12b | llama.cpp | 2.8s | 9.1s | 19.0s | 99 (full GPU) |
| gemma3:12b | Ollama | 4.6s | 12.5s | 21.8s | auto |
| gemma3:4b | Ollama | ~3s | ~10s | ~12s | auto |

## VRAM Analysis

- Model size (Q3_K_M): 14 GB
- Arc B50 VRAM: 16 GB
- Full GPU offload (99 layers): **FAILED** — `ErrorOutOfDeviceMemory` with 547 MB allocation
- Partial offload (25 layers): **PASS** — model split between GPU and CPU
- Inference speed: ~3 tok/s (vs ~10-15 tok/s for gemma3:12b full GPU)

## Quality Assessment

Despite being 15-25x slower than gemma3:12b, Gemma4 31B produces noticeably richer output:
- Strategy classifier: higher confidence (0.9 vs 0.8), more detailed reasoning citing both enrichment sources
- Close trade analysis: comprehensive assessment with clear thesis evaluation and actionable lessons
- Token output ~3-5x higher per response (more thorough analysis)

## Verdict

| Criterion | Assessment |
|-----------|-----------|
| Output quality | Excellent — best of all tested models |
| Speed | Too slow for batch classification (4+ minutes per trade) |
| VRAM | Doesn't fit fully on GPU (needs hybrid CPU/GPU) |
| Production viability | **NO** — 236s per classifier call makes 55-trade batch take 3.5 hours |
| Use case | Deep review / adjudication of important trades only |
| Recommended role | **Offline quality reviewer** — weekend/overnight deep analysis |

## Recommendation

- **Do NOT use for production classification** — too slow at 3-4 minutes per trade
- **Consider for overnight deep review** — quality is superior to gemma3:12b
- **Possible use: trade_close_llm_analyzer quality pass** — run on small batches (5-10 trades) overnight
- **Q4_K_M (17 GB) would not fit** — stick with Q3_K_M if using this model
- **Production remains gemma3:12b** on Ollama GPU

## Safety

- No production routing changed
- No .env modified  
- No DB writes
- llama-server stopped after canary
- Ollama health check PASS after cleanup
