# Phase 3 — Evaluation Report

**Date:** 2026-05-14
**Status:** HOLD — candidate underperformed in smoke test

## Candidate

`gemma4:e4b` — installed, 9.6 GB (larger than documented 3-4 GB)

## Smoke Test

**POOR** — model produced irrelevant output instead of following summarization instruction.
- Prompt: "Summarize this in 3 concise bullets: A long transcript discusses earnings, sector rotation, and risk management."
- Output: off-topic text about comparison requests, not a summary
- Generation: 120 tokens in 8.2s
- Load time: ~54s
- Total: 62s

## Pilot

Not run — smoke test quality insufficient to justify pilot.

## Critical Findings

1. **9.6 GB disk** — 2-3x larger than documented estimate of 3-4 GB
2. **Cannot coexist with qwen3:14b** — 9.6 + 10 = 19.6 GB exceeds 16 GB VRAM
3. **Poor instruction following** — did not summarize as requested
4. **Same lifecycle burden as gemma3-overnight** — requires evict/restore

## Recommendation

**HOLD Phase 3.** Options for operator:
1. Run additional smoke tests with different prompts to rule out prompt format issue
2. Try a smaller model (gemma3:4b, phi-4-mini, or similar ~2-4 GB model)
3. Keep qwen3:14b for all local inference — it handles content tasks adequately
4. Wait for gemma4 ecosystem maturity (revisit 2026-08-11 per strategy doc)
5. Remove gemma4:e4b to reclaim 9.6 GB disk: `ollama rm gemma4:e4b`

## Production Impact

None. Smoke test only. Production models restored (qwen3:14b + nomic-embed-text).
