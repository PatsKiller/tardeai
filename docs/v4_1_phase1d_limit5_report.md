# Phase 1D — Controlled Limit-5 Expansion Report

**Date:** 2026-05-12 08:57-09:05 ET
**Operator:** johnclaw (manual invocation)
**Commit:** `867b7a0` (Phase 1D: raise gemma pilot max limit from 3 to 5)

---

## Summary

First --limit 5 test of `gemma3-overnight` via the pilot wrapper completed successfully.
All 5 symbols classified. GPU lifecycle clean. qwen3:14b + nomic-embed-text fully restored.
No cron, no persistent routing, no .env changes.

## Pilot Run

| Metric | Value |
|--------|-------|
| Command | `./scripts/run_batch_overnight_gemma_pilot.sh --limit 5` |
| Symbols classified | 5 (ACH, ACNT, ACTU, ADNT, ADUR) |
| Wall time | **461 seconds** (7 min 41 sec) |
| Timeout cap | 10 minutes |
| Under timeout? | **YES** — 2 min 19 sec margin |
| Pilot exit code | 0 |

## Per-Symbol Timing

| Symbol | Timestamp | Elapsed | Strategies |
|--------|-----------|---------|------------|
| ACH | 08:59:19 | ~85s (includes gemma load) | gap_and_go(95%), momentum_scalp(95%), speculative_growth(95%), recovery_watch(90%), sector_rotation(90%) |
| ACNT | 09:00:34 | ~75s | speculative_growth(90%), swing_breakout(90%), swing_trade(90%), earnings_catalyst(80%), recovery_watch(60%) |
| ACTU | 09:01:56 | ~81s | gap_and_go(95%), speculative_growth(90%), recovery_watch(70%), sector_rotation(70%), earnings_catalyst(65%) |
| ADNT | 09:03:43 | ~107s | earnings_catalyst(95%), dividend_growth_compounder(90%), sector_rotation(90%), international_dividend(80%), gap_and_go(70%) |
| ADUR | 09:05:31 | ~108s | earnings_catalyst(95%), dividend_growth_compounder(90%), sector_rotation(90%), international_dividend(80%), gap_and_go(75%) |

**Average per-symbol:** ~91s (including first-symbol cold load overhead)
**Steady-state per-symbol:** ~93s (symbols 2-5 average, after gemma warm)

## GPU Behavior

| Phase | Model | VRAM | CPU Spill | Total |
|-------|-------|------|-----------|-------|
| Pre-swap | qwen3:14b | 9.4 GB | 0 | 9.4 GB |
| Pre-swap | nomic-embed-text | 0.54 GB | 0 | 0.54 GB |
| During pilot | gemma3-overnight | **13.64 GB** | **4.79 GB** | 18.43 GB |
| Post-restore | qwen3:14b | 9.4 GB | 0 | 9.4 GB |
| Post-restore | nomic-embed-text | 0.54 GB | 0 | 0.54 GB |

**gemma3-overnight VRAM profile:** 13.64 GB GPU (74.7% of 18.27 GB), 4.79 GB CPU spillover.
Consistent with Phase 1 (13.75 GB), Phase 1C (13.64 GB) observations.

## Strategy Distribution (5 symbols)

| Strategy | Count |
|----------|-------|
| gap_and_go | 4 |
| sector_rotation | 4 |
| earnings_catalyst | 4 |
| speculative_growth | 3 |
| recovery_watch | 3 |
| dividend_growth_compounder | 2 |
| international_dividend | 2 |
| momentum_scalp | 1 |
| swing_breakout | 1 |
| swing_trade | 1 |

## Safety Validation

| Check | Result |
|-------|--------|
| ALPACA_MODE | paper |
| LLM_DISABLE_LIVE_EXECUTION | true |
| Holdings guard | $1,192,663 — PASSED |
| Active hours gate | PASSED (outside market hours) |
| qwen3:14b restore | **ok** |
| nomic-embed-text restore | **ok** |
| gemma3-overnight unloaded | **yes** (not in gpu-status) |
| Cron entries added | **none** |
| .env routing changes | **none** (LOCAL_LLM_MODEL=qwen3:14b unchanged) |
| STANDARD routing | unchanged |
| REALTIME routing | unchanged |
| EMBEDDING routing | unchanged |
| MEDIA_CONTENT routing | unchanged |
| CRITICAL_CLOUD routing | unchanged |

## Scaling Analysis

| Limit | Observed/Extrapolated | Timeout Margin |
|-------|----------------------|----------------|
| 1 | 99s | 8 min 21 sec |
| 2 | 2 min 42 sec | 7 min 18 sec |
| 3 | ~4 min 33 sec (extrapolated) | 5 min 27 sec |
| **5** | **7 min 41 sec (actual)** | **2 min 19 sec** |
| 7 | ~10 min 47 sec (extrapolated) | WOULD TIMEOUT |
| 10 | ~15 min 30 sec (extrapolated) | WOULD TIMEOUT |

**Conclusion:** --limit 5 is the practical ceiling under the current 10-minute timeout.
A limit of 7+ would require raising the timeout or accepting occasional timeout kills.

## Recommendation

**Phase 1 should stop at manual --limit 5.** Rationale:

1. **7m41s is close to the 10m cap.** Variation in LLM response time could push occasional runs past 10m.
2. **No urgency for nightly automation.** The overnight batch already classifies via qwen3:14b. Gemma adds diversity, not coverage.
3. **GPU swap cost is non-trivial.** Each pilot requires evicting qwen → loading gemma → running → unloading gemma → restoring qwen+nomic. During this window (~8 min), the system has no local LLM for other callers.
4. **Phase 2 prerequisite:** Before scheduling a nightly cron, the system should have a model-swap lock that pauses other LLM callers during the gemma window. Without that, overnight crons hitting Ollama during the swap will fail or fall back to cloud.

**If operator wants to proceed to a scheduled once-nightly pilot later:**
- Raise timeout to 12m
- Add Ollama queue drain check before swap (ensure no pending requests)
- Schedule at 2:00-3:00 AM when cron traffic is lowest
- Still require operator approval before enabling cron
