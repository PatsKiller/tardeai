# Gemma3:12b GPU Workload Canary Report

**Date:** 2026-05-28
**Mode:** GPU/Vulkan (num_gpu=-1, Arc B50)
**Ollama:** 0.24.0

## Results

| Test | Status | Latency | Tokens | Fenced JSON | Notes |
|------|--------|---------|--------|-------------|-------|
| basic_json | **PASS** | 4.6s | 15 | Yes | Returned `{"answer":4,"status":"ok"}` inside markdown fences |
| strategy_classifier | **PASS** | 12.5s | 132 | Yes | Valid strategy_id, confidence, reasoning, evidence_used |
| close_trade_analysis | **PASS** | 21.8s | 254 | Yes | Valid summary, thesis/execution/stop assessments, lessons |

**Score: 3/3 PASS**

## VRAM Footprint

- **9.75 GB** (vs gemma3:4b at 7.2 GB)
- Arc B50 has ~15.9 GB VRAM — leaves ~6 GB headroom
- MAX_LOADED_MODELS=1 must remain enforced — cannot coexist with another generation model

## Output Quality

All three outputs were valid structured JSON wrapped in markdown fences (` ```json ... ``` `). The parser correctly strips fences. Output quality is comparable to gemma3:4b:

- Strategy classifier produced correct strategy_id with enrichment evidence
- Close trade analysis produced meaningful assessments with lessons
- Token counts are moderate (132-254) — not excessively verbose

## Latency Comparison

| Model | basic_json | strategy_classifier | close_trade_analysis |
|-------|-----------|--------------------|--------------------|
| gemma3:4b (GPU) | ~3s | ~10s | ~12s |
| **gemma3:12b (GPU)** | **4.6s** | **12.5s** | **21.8s** |
| gemma4:e2b (CPU) | 12.2s | 45.2s | 45.3s |

gemma3:12b is ~1.5-2x slower than gemma3:4b on GPU. Still well within classifier timeout (90s) and analyzer timeout (120s).

## Markdown-Fenced JSON

All 3 responses used markdown fences. The existing JSON parser in trade_strategy_classifier.py and trade_close_llm_analyzer.py already handles fenced JSON — no parser changes needed.

## Recommendation

**Review-only model.** gemma3:12b passes all workload canaries on GPU and produces good quality output. However:

1. **Not yet production default** — gemma3:4b is proven stable over 55+ classifier applies and multiple batch runs. gemma3:12b has only 3 canary tests.
2. **Higher VRAM** — 9.75 GB vs 7.2 GB leaves less headroom for VRAM spikes.
3. **Slower** — 1.5-2x latency increase on all workloads.
4. **Promotion path:** Run gemma3:12b on a 10-20 trade dry-run classifier batch. If output quality matches or exceeds gemma3:4b with no failures, consider promoting to production default.

## Status Decision

| Option | Verdict |
|--------|---------|
| Production default | Not yet |
| **Review-only model** | **Yes — approved for dry-run testing** |
| Disabled | No — it works on GPU |

## Post-Canary State

- gemma3:12b unloaded after tests
- gemma3:4b reloaded by health check
- Health check: PASS 7/7
- No .env changes
- No DB writes
