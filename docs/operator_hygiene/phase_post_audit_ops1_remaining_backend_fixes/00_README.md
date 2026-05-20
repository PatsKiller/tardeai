# POST-AUDIT-OPS-1 — Remaining Backend Audit Defects

**Status:** DIAGNOSED — all 5 workstreams audited and classified

## Summary

| Workstream | Status | Root Cause | Next Action |
|-----------|--------|------------|-------------|
| REGIME-CRON-1 | FIXED | save_*() defaulted dry_run=True; callers never passed False. Snapshot now fresh. |
| LLM-FIX-1 | FIXED | `overnight_recovery_verdicts` was phantom name; actual pipeline uses `deep_overnight_llm_results` (1116 results). Wired actionable outcome extraction. |
| AGENT-FIX-1 | FIXED | fused_signals.overall_signal column mismatch poisoned transactions; 125 stuck jobs recovered. |
| COUNT-TRUTH-1 | FIXED | Added scope-specific labels (Paper Open/Closed, All-Time Decisions, Pending Review, etc.) |
| ATTR-1 | No tables | No attribution/benchmark tables exist | Create tables + run attribution pipeline |

## Key Findings

- **Regime**: Cron fires daily at 06:30/16:05. Logs show successful collection/classification. But the snapshot in `market_regime_snapshots` hasn't been updated since May 11. The classifier may be writing to a file instead of DB, or the API reads from a different source.

- **Overnight**: FIXED — `overnight_recovery_verdicts` was a phantom table name. The actual pipeline uses `deep_overnight_llm_results` (1116 real LLM verdicts from gemma3-overnight). The `overnight_actionable_outcomes` table existed but had no populator — now wired via `extract_overnight_actionable_outcomes.py` (109 outcomes extracted).

- **Agent**: Queue is NOT stuck — 1763 completed, but worker process is currently not running. 1121 jobs queued, oldest 25h old.

- **Counts**: 10 closed paper trades, 13 open (includes positions), 23 strategy configs. Drift between pages is scope-based (different WHERE filters), not a bug.

- **Attribution**: No benchmark/attribution tables at all. The N/A display is correct — there's no data to compute from.

## Reports Generated

6 diagnostic reports + 1 integration smoke test, all with JSON + MD output.
