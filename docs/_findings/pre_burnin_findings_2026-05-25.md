# Pre-Burn-In Findings (2026-05-25)

Status:      HISTORICAL
as_of:       2026-05-23T16:41:31-04:00
Measured at: efcc51365 / not measured

Three findings from final Sunday audit before Monday 09:35 ET ATM burn-in.

## F1: Portfolio Heat 7.1% (ACCEPTED)

**Finding:** Portfolio heat (open risk as % of equity) shows 7.1%, above the 5% target.
**Root Cause:** Retirement positions (Schwab/Fidelity/Vanguard) have no stops because they are untouchable long-term holds. The heat calc includes them.
**Decision:** Accept for burn-in. ATM only trades Alpaca paper with its own caps (0.10% per trade, 0.25% daily loss pause). Retirement positions don't interact with ATM risk limits.
**Action:** None required. Monitor during burn-in week.

## F2: Watchdog 14d Silent (RESOLVED)

**Finding:** Pipeline health showed watchdog stage with no activity for 14 days.
**Root Cause:** Registry name mismatch. The `data_gap_resolver` cron runs successfully under a different pipeline stage key than the hardcoded "watchdog" name in pipeline health. Confirmed via `pipeline_stage_runs` query — `data_gap_resolver` has recent runs.
**Decision:** Not a real gap. The resolver is running.
**Action:** None required for burn-in. Future: align stage key naming.

## F3: Agent Collaboration Tile Stale (FIXED)

**Finding:** Agent dashboard showed Alex last_run 2026-05-10, Aegis last_run 2026-05-10 — both 12+ days stale despite active crons.
**Root Cause:** Three bugs in `_agents_summary()` enrichment queries:
1. `cio_decisions WHERE created_by ILIKE '%alex%'` — column `created_by` does not exist. Alex is the sole writer; no WHERE needed.
2. `alert_events WHERE source ILIKE '%alex%'` — column is `source_script`, not `source`. And Alex doesn't write to alert_events anyway (returns NULL).
3. `aegis_portfolio_briefs MAX(created_at)` — column is `observed_at`, not `created_at`. Plus a duplicate enrichment block with the same wrong column.

All three queries silently failed (caught by `except Exception: pass`), so enrichment never ran.

**Fix (commit 5bae51d):**
```python
_AGENT_HOME_TABLES = [
    ("alex", "SELECT COUNT(*) as cnt, MAX(created_at) as latest FROM cio_decisions"),
    ("aegis", "SELECT COUNT(*) as cnt, MAX(observed_at) as latest FROM aegis_portfolio_briefs"),
]
```
Removed dead `alert_events`/`tax_agent` queries and duplicate aegis block.

**Result:**
- Alex: 2026-05-10 → 2026-05-20 (732 decisions)
- Aegis: 2026-05-10 → 2026-05-22 (1,549 briefs)
