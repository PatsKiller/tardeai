# Self-Healing Health Agent — Final Validation Report

**Date:** 2026-05-29

## Validation Summary

| Area | Status | Detail |
|------|--------|--------|
| Health agent enrich-before-reject | **PASS** | Old `auto_enrichment_stuck_2h` path removed. New logic: enrich up to 3x, reject only after 3 failures or 6h |
| Cron coverage | **PASS** | Enrichment runs `*/10 4-19`. No uncovered window for proposal creation |
| Claude Code escalation queue | **PASS** | Queue schema includes fixable flag, retry_cmd, Telegram notification |
| Claude Code retry_cmd execution | **WARN (P1)** | Handler passes retry_cmd to Claude CLI prompt but does not execute it directly |
| Live state validation | **PASS** | 0 currently stuck proposals, 0 rejected by old path since fix |
| Dry-run simulation | **PASS** | Query logic confirmed: all SQL paths correct, old rejection paths removed |
| Code review | **PASS** | No residual `auto_enrichment_stuck_2h` or `auto_stale_4h` in code |
| Can this exact failure recur? | **NO** | Enrichment cron now covers 4-19, health agent enriches before rejecting |

## Code Review — Enrich-Before-Reject Logic

**File:** `scripts/system_health_agent.py` lines 793-857

### Flow verified:

```
Step 1: SELECT PENDING proposals >30 min old, packet_state IN (NEW, MISSING_DATA, ENRICHING),
        enrichment_attempt_count < 3
        → Trigger auto_enrichment_runner.py --force-all
        → INCREMENT enrichment_attempt_count for each proposal
        → DO NOT REJECT

Step 2: UPDATE to REJECTED only WHERE enrichment_attempt_count >= 3
        AND age > 2 hours AND packet_state still stuck
        → reason: auto_enrichment_failed_3x

Step 3: UPDATE to REJECTED WHERE age > 6 hours (hard safety net)
        → reason: auto_stale_6h
```

### Old paths confirmed removed:
- `auto_enrichment_stuck_2h` — **REMOVED** (was: reject after 2h with 0 attempts)
- `auto_stale_4h` — **REMOVED** (replaced by `auto_stale_6h`)

### DB fields used:
- `enrichment_attempt_count` (integer, nullable, default 0)
- `enrichment_last_attempt_at` (timestamp)
- `packet_state` (enum: NEW, ENRICHING, MISSING_DATA, COMPLETE, etc.)
- `approval_allowed` (boolean)

### Impossible to reject with 0 attempts: **CONFIRMED**
Step 2 requires `enrichment_attempt_count >= 3`. Step 3 requires age > 6h. Neither path can reject a proposal with 0 enrichment attempts that is younger than 6h.

## Cron Coverage

| Action | Cron | Coverage |
|--------|------|----------|
| Pre-market proposals | `0 4 * * 1-5` (atp2_research_cycle) | 4:00 AM |
| Market proposals | `0 9,10,12,14,16 * * 1-5` (orchestrator) | 9 AM - 4 PM |
| **Enrichment** | `*/10 4-19 * * 1-5` (auto_enrichment + proposal_enrichment) | **4 AM - 7:50 PM** |
| Health agent | `*/5 9-20 * * 1-5` + `0 7 * * 1-5` | 7 AM single + 9-20 every 5 min |
| Escalation handler | `*/15 7-20 * * 1-5` | 7 AM - 8 PM every 15 min |

**4-9 AM gap CLOSED:** Enrichment now runs from 4 AM. Health agent runs at 7 AM (single check) and 9 AM+ (continuous). Minor note: health agent doesn't run 4-7 AM or 7:05-8:55 AM, but enrichment cron handles proposals independently — health agent is a safety net, not the primary enrichment driver.

## Claude Code Escalation Loop

### What works:
- Queue written to `logs/claude_escalation_queue.json` with fixable flag
- Enrichment-stuck proposals with 2+ attempts are escalated
- Local LLM diagnosis attempted for fixable items
- Claude Code CLI invoked via `claude -p` (5 min timeout)
- Intervention logged to `claude_interventions` table
- Telegram notification sent with result
- Queue cleared after processing

### P1 Gap: retry_cmd not executed directly
The handler includes `retry_cmd` in the problem text sent to Claude Code CLI, but does not execute it directly with `subprocess.run()`. Claude Code may or may not run it depending on prompt interpretation. This is acceptable for now because:
1. The health agent itself already runs the enrichment retry (Level 3)
2. Claude Code escalation is Level 4 (last resort)
3. The retry_cmd is in the prompt so Claude can choose to run it

**Recommendation:** Add direct `subprocess.run(retry_cmd)` before Claude Code invocation for items marked `fixable: true`. This removes dependency on Claude Code prompt interpretation.

## Live State Validation

| Metric | Value |
|--------|-------|
| Currently stuck proposals | 0 |
| Rejected by old `auto_enrichment_stuck_2h` since fix | 0 |
| Rejected with 0 enrichment attempts (enrichment reason) | 0 |
| Proposals with enrichment attempts today | 1 (CRSR, enrichment_status=COMPLETE) |
| Escalation queue items | 2 (both portfolio_risk, informational) |
| Fixable items in queue | 0 |

## Today's Rejection Analysis

| Reason | Count | Analysis |
|--------|-------|----------|
| cooldown_cleared_by_operator | 6 | Old 4 AM batch, rejected at 7 AM BEFORE fix was deployed |
| atm_same_day_skip | 2 | ATM cadence policy, not enrichment issue |
| auto_stale_price_drift_* | 4 | Price moved too far from proposed entry, correct behavior |

None of today's rejections were caused by the fixed bug. The fix has not yet been tested with a real stuck proposal (none occurred since deployment).

## UI/API Visibility

| Metric | Exposed in API | Visible in UI |
|--------|---------------|---------------|
| enrichment_attempt_count | YES (api_v2.py line 8051) | Likely (proposal detail) |
| Stuck proposals | No dedicated endpoint | P1 follow-up |
| Escalation queue status | No dedicated endpoint | P1 follow-up |
| Rejected-before-retry count | No dedicated endpoint | P1 follow-up |

## Remaining Gaps

### P0 (None)
All critical paths are fixed.

### P1
1. **Escalation handler retry_cmd execution**: Handler should run `retry_cmd` directly for fixable items before invoking Claude Code
2. **Health agent 4-7 AM coverage**: Only runs at 7 AM, not continuously. Enrichment cron covers this independently.
3. **UI dashboard for enrichment health**: No dedicated view showing stuck proposals, enrichment attempts, or escalation queue
4. **Test coverage**: No unit tests for enrich-before-reject logic

## Conclusion

The exact failure (4 AM proposals rejected with 0 enrichment attempts) **cannot recur** with the current code:
1. Enrichment cron now covers 4 AM - 7:50 PM
2. Health agent enriches before rejecting (3 attempts minimum)
3. Old 2h/4h rejection paths are removed
4. Enrichment-stuck proposals escalate to Claude Code queue
