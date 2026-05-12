# Phase 1C — Controlled Expansion Report

**Date:** 2026-05-12 08:10 ET
**Operator:** Manual execution only. No cron scheduled.

## Summary

Expanded gemma3-overnight pilot from 1 symbol to 2 symbols. Pilot completed successfully with clean GPU lifecycle.

## Script Changes

**File:** `scripts/run_batch_overnight_gemma_pilot.sh`

- Fixed `--limit` argument parsing (was `${1:---limit 1}` which only captured `$1`, dropping the value)
- Replaced with proper `while/case` arg parser supporting `--limit N`
- Default remains `--limit 1`
- Added `MAX_LIMIT=3` enforcement — exits with error if `--limit` exceeds 3
- Input validation: must be positive integer
- Updated header comments and log messages from Phase 1B to Phase 1C
- All existing safety gates preserved unchanged

## Pilot Run: --limit 2

```
Start:  2026-05-12 08:10:56
End:    2026-05-12 08:13:45
Total:  2 min 49 sec
```

### Safety Gates (all passed)
- ALPACA_MODE=paper
- LLM_DISABLE_LIVE_EXECUTION=true
- Holdings: $1,191,948 (>$1M guard)
- Active hours gate: PASSED (outside market hours)

### GPU Lifecycle

| Phase | Models Loaded | VRAM |
|-------|--------------|------|
| Before swap | qwen3:14b | 9.4 GB |
| During pilot | gemma3-overnight | 13.64 GB VRAM + 4.79 GB CPU spill (18.43 GB total) |
| After restore | qwen3:14b + nomic-embed-text | 9.4 GB + 0.54 GB |

### Classification Results

```
Classified: 2 symbols
Multi-strategy matches: 2

Strategy distribution:
  speculative_growth             2
  recovery_watch                 2
  gap_and_go                     1
  momentum_scalp                 1
  sector_rotation                1
  swing_breakout                 1
  swing_trade                    1
  earnings_catalyst              1
```

### Timing

- Phase 1B (1 symbol): ~2 min 11 sec (22:13:20 to 22:15:31)
- Phase 1C (2 symbols): ~2 min 42 sec (08:10:58 to 08:13:40)
- Per-symbol overhead: ~31 sec additional for 2nd symbol
- Well within 10m timeout

## Post-Run Validation

| Check | Result |
|-------|--------|
| GPU state | qwen3:14b (9.4 GB) + nomic-embed-text (0.54 GB) — correct |
| verify_llm_providers.py | Local: usable=True, degraded=False |
| ALPACA_MODE | paper (unchanged) |
| LLM_DISABLE_LIVE_EXECUTION | true (unchanged) |
| Holdings | $1,191,948 (unchanged) |
| gemma3-overnight loaded | No — fully unloaded |
| Cron entries | No changes — no gemma cron exists |
| .env routing | No changes — BATCH_OVERNIGHT not set |

## Limit 3 Recommendation

**Recommended: YES** — with caution.

Rationale:
- 2-symbol run took 2m42s, well within 10m timeout
- Linear extrapolation: 3 symbols ~3m13s (still under 5 minutes)
- GPU swap/restore clean on both runs
- gemma3-overnight VRAM profile unchanged (13.64 GB GPU)
- No resource contention observed

Suggested next step: `./scripts/run_batch_overnight_gemma_pilot.sh --limit 3` as next manual test.

## What Was NOT Changed

- No cron entries added, modified, or scheduled
- No .env changes (BATCH_OVERNIGHT, routing, keys)
- No changes to STANDARD, REALTIME, EMBEDDING, MEDIA_CONTENT, or CRITICAL_CLOUD
- No broker, holdings, or execution behavior changes
- No persistent model routing changes
- qwen3:14b remains the default LOCAL_LLM_MODEL
