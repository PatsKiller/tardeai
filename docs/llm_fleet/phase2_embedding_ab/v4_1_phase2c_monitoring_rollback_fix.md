# Phase 2C — Monitoring and Rollback Fix

**Date:** 2026-05-14
**Type:** Operational documentation fix

## Issues Fixed

1. **Monitor command shell safety** — `grep -E` and its pattern must stay on the same line to avoid shell splitting. The monitor `watch` command was corrected and wrapped in a helper script.

2. **Rollback completeness** — The original rollback only removed `--enable-hybrid-rag` but could leave behind related flags (`--hybrid-prefetch-limit`, `--hybrid-job-types`, etc.). Rollback now prefers restoring the saved pre-change crontab backup, with a comprehensive sed fallback.

## Helper Scripts Created

| Script | Purpose |
|--------|---------|
| `scripts/monitor_phase2c_hybrid_nightly.sh` | Watch Phase 2C hybrid nightly run (read-only) |
| `scripts/rollback_phase2c_hybrid_nightly.sh` | Disable Phase 2C hybrid (restore pre-change crontab) |

## Rollback Policy

1. **Preferred:** Restore `docs/llm_fleet/phase2_embedding_ab/crontab_pre_phase2c_nightly_hybrid_enable.txt`
2. **Fallback:** Remove all hybrid flags via multi-pattern sed
3. **Scope:** Removes Phase 2C nightly hybrid only. Phase 1 base schedule preserved.
4. **Friday:** Unchanged unless explicitly enabled later.

## No Cron Change Made

This fix updates documentation and adds helper scripts only. No cron schedule was modified.

## Production Impact

None. Production RAG routing, embeddings, .env, broker/holdings/execution unchanged.
Phase 2D remains blocked.
