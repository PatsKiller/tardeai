# Phase 1 Pilot Report — gemma3:27b BATCH_OVERNIGHT

**Date:** 2026-05-11 22:00-22:05 ET
**Operator authorization:** "Begin Phase 1 pilot only"

## Summary

gemma3:27b was successfully tested as a BATCH_OVERNIGHT model. It loaded, generated
coherent output, and ran the pilot script (`multi_strategy_classifier.py --batch --llm --limit 1`)
to completion. qwen3:14b was fully restored afterward.

## VRAM Assessment

| Metric | Value |
|--------|-------|
| gemma3:27b total size | 18.26 GB |
| VRAM allocated | 13.75 GB (75.3% GPU offload) |
| CPU spillover | 4.51 GB (24.7%) |
| nomic-embed-text | evicted during gemma load |
| qwen3:14b | evicted before gemma load |
| VRAM free during gemma | 2.25 GB |

**Key finding:** gemma3:27b does NOT fit entirely in 16 GB VRAM. ~25% of layers spill
to CPU. This causes measurably slower throughput but remains functional for batch work.

## Performance Comparison

| Model | Test | eval_count | eval_time | tok/s | total_time |
|-------|------|-----------|-----------|-------|------------|
| qwen3:14b | Agent-sized | 114 | 11.5s | 9.9 | 14.6s |
| gemma3:27b | Tiny (5 tok) | 5 | 0.72s | 6.9 | 5.4s |
| gemma3:27b | Agent-sized (200 tok) | 200 | 37.7s | 5.3 | 39.7s |

**gemma3:27b is ~53% of qwen3:14b throughput** due to CPU spillover. Acceptable for
non-time-critical overnight batch work.

## Pilot Script Results

**Script:** `multi_strategy_classifier.py --batch --llm --limit 1`
**Model override:** `LOCAL_LLM_MODEL=gemma3:27b` (shell-only, not persisted)
**Runtime:** 99 seconds
**Result:** Successfully classified ACH across 5 strategies (gap_and_go, momentum_scalp,
speculative_growth, recovery_watch, sector_rotation) with 90-95% confidence.
**Quality:** Output was coherent, well-structured, and matched expected classification format.

## GPU Lifecycle

| Step | Result | Time |
|------|--------|------|
| gate_batch_overnight() | PASSED (outside active hours) | <1ms |
| cooldown qwen3:14b | OK (keep_alive=0 + wait) | ~3s |
| gemma3:27b smoke test | OK (HTTP 200, 5.4s) | 5.4s |
| gemma3:27b agent test | OK (HTTP 200, 39.7s) | 39.7s |
| Pilot script run | OK (1 symbol classified) | 99s |
| cooldown gemma3:27b | OK (unloaded) | <1s |
| warmup qwen3:14b | OK (loaded in 2.15s) | 2.15s |
| warmup nomic-embed-text | OK (via /api/embeddings) | <1s |

**Restore verified:** qwen3:14b (9.4GB) + nomic-embed-text (0.54GB) = 9.94GB used.

## What Was NOT Changed

- `.env` was NOT modified — model override was shell-only
- `LLM_BATCH_OVERNIGHT` env var was NOT set
- No persistent config changes
- No model routing changes
- No cron changes
- No broker, holdings, or execution changes
- No embeddings or RAG changes
- `ALPACA_MODE=paper`, `LLM_DISABLE_LIVE_EXECUTION=true` unchanged
- Holdings: $1,191,456 (guard passed)

## Abort Conditions Observed

- `can_load()` returned False for gemma3:27b — expected, VRAM insufficient for full offload
- CPU spillover confirmed (~25%) — degraded but functional
- nomic-embed-text evicted during gemma load — restored after cooldown

## Go/No-Go for Phase 1 Expansion

**Conditional GO** with caveats:

1. **gemma3:27b works** for BATCH_OVERNIGHT classification at 5.3 tok/s
2. **GPU lifecycle works** — evict/load/restore cycle completed cleanly
3. **Quality is acceptable** — output was coherent and well-formatted
4. **CPU spillover is the constraint** — 25% on CPU means ~50% slower than qwen3:14b

**Caveats for expansion:**
- Must create `gemma3-overnight` Modelfile (keep_alive=0, num_ctx=8192) before persistent use
- Must add `LLM_BATCH_OVERNIGHT=gemma3:27b` to `.env` only after Modelfile is created
- Must wrap overnight batch crons in lifecycle (warmup before, cooldown+restore after)
- Must verify nomic-embed-text restore works with the lifecycle wrapper
- Consider whether 5.3 tok/s is sufficient for batch workloads with 10+ symbols
