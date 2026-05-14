# Phase 2C — Friday Extended Hybrid Enablement

**Date:** 2026-05-14

## Change

**Old Friday cron:**
```
0 16 * * 5 ... bash scripts/run_deep_overnight_llm_window.sh --force-window --max-jobs 200 --allow-over-hard-max >> logs/deep_llm_friday_extended.log 2>&1
```

**New Friday cron:**
```
0 16 * * 5 ... bash scripts/run_deep_overnight_llm_window.sh --enable-hybrid-rag --force-window --max-jobs 200 --allow-over-hard-max >> logs/deep_llm_friday_extended.log 2>&1
```

## Configuration

| Setting | Value |
|---------|-------|
| Max jobs | 200 (unchanged) |
| Hybrid RAG | Enabled |
| Two-stage lifecycle | Yes |
| Prefetch limit | Default (100) |
| Hybrid final-k | 10 |

## Daily Line

Unchanged (already has `--enable-hybrid-rag` from prior enablement).

## Rollback

```bash
./scripts/rollback_phase2c_hybrid_nightly.sh --friday
./scripts/rollback_phase2c_hybrid_nightly.sh --friday --dry-run  # preview
```

## Production Impact

None. Global RAG routing, .env, broker/holdings/execution unchanged.
