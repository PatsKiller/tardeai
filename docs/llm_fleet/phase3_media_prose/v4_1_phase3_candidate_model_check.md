# Phase 3 — Candidate Model Check

**Date:** 2026-05-14

## Candidate

`gemma4:e4b` — documented in LLM Fleet Strategy v4.1 Final, Section "Phase 3 — Media/Content"

## Installation Status

**INSTALLED** (2026-05-14)

## Actual Specs

| Metric | Value |
|--------|-------|
| Model | gemma4:e4b |
| Disk | **9.6 GB** (larger than documented 3-4 GB estimate) |
| VRAM | ~9.6 GB resident (does NOT fit alongside qwen3:14b on 16 GB) |
| Can coexist with qwen3:14b | **NO** — 9.6 + 10 = 19.6 GB exceeds 16 GB VRAM |
| Load time | ~54 seconds |
| Architecture | Dense |

## Smoke Test Result

**POOR QUALITY** — model generated irrelevant comparison instructions instead of summarizing the provided transcript topic. The prompt was clear ("Summarize this in 3 concise bullets") but the model produced off-topic output about comparison requests.

- Generation latency: 8.2s for 120 tokens
- Total time: 62s (including ~54s model load)
- Output: incoherent, did not follow instruction

## Critical Findings

1. **Size mismatch**: 9.6 GB actual vs 3-4 GB documented. This changes the coexistence model — gemma4:e4b CANNOT coexist with qwen3:14b on 16 GB VRAM.
2. **Quality concern**: smoke test produced irrelevant output. May need different prompt format or the model may not be suitable.
3. **VRAM impact**: would require same evict/restore lifecycle as gemma3-overnight.

## Recommendation

**HOLD** — gemma4:e4b is larger than expected and showed poor instruction-following in smoke test. Options:
1. Run additional smoke tests with different prompt formats
2. Try a smaller model (e.g., gemma3:4b or phi-4-mini)
3. Keep qwen3:14b for all local inference and accept current workload distribution
4. Wait for gemma4 ecosystem to mature (revisit date: 2026-08-11 per strategy doc)
