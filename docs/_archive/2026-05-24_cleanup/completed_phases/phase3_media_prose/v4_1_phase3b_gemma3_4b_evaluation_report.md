# Phase 3B — gemma3:4b Evaluation Report

**Date:** 2026-05-14
**Status:** CANDIDATE_BETTER — gemma3:4b passes Phase 3 lightweight model goal

## Why gemma4:e4b Was Rejected

- Actual size: 9.6 GB (expected 3-4 GB)
- Cannot coexist with qwen3:14b on 16 GB VRAM
- No quality advantage over qwen3:14b
- Removed to reclaim disk (~9 GB)

## gemma3:4b Results

| Metric | Baseline (qwen3 /no_think) | Candidate (gemma3:4b) |
|--------|---------------------------|----------------------|
| Avg score | 3.2 | **3.9** |
| Avg latency | 28,221ms | **6,870ms** (4x faster) |
| Tests | 4 (1 timeout) | 12 (0 timeouts) |
| Actual output | 1/5 non-empty | **12/12 non-empty** |
| Verdict | — | **CANDIDATE_BETTER** |

## Key Findings

1. **Quality**: gemma3:4b scored 3.9 vs qwen3 3.2 — consistently produced useful, formatted output
2. **Latency**: 4x faster (6.9s vs 28.2s). Classification in 520ms, news digest in 1.9s
3. **Size**: 3.3 GB — **fits alongside qwen3:14b** (3.3 + 10 = 13.3 GB < 16 GB VRAM)
4. **Reliability**: 12/12 tests produced output vs qwen3 which returned empty on 4/5 tests
5. **Formatting**: scored 4.0 on most tests (bullets, classification, concise prose)
6. **Safety**: no unwanted trade recommendations in any test

## VRAM/Lifecycle Verdict

**PASS** — 3.3 GB can coexist with qwen3:14b on 16 GB Intel Arc B50. No evict/restore required for normal use.

## Recommendation

**Continue Phase 3 pilot with gemma3:4b.** It meets all Phase 3 criteria:
- Lightweight (3.3 GB)
- Can coexist with qwen3:14b
- Better quality than qwen3 for media/prose tasks
- 4x faster
- Reliable output formatting

Next steps:
1. Create Phase 3 routing config for approved media/prose workflows
2. Run limited offline pilot (20 content samples)
3. Evaluate coexistence under real workload
4. Route selected workflows if pilot passes

## Production Impact

None. Production models restored (qwen3:14b + nomic-embed-text).
