# Phase 67E — Maria Research Staleness True-Fix Audit

**Date:** 2026-06-01
**Status:** COMPLETE — verification gate design

## Problem

Escalation loop reports "fixed" for mariaresearch staleness, but alert repeats — indicating no actual fresh output was produced.

## Root Cause

LLM-based escalation can classify an issue as "analyzed" and mark it "fixed" based on reasoning alone, without verifying that the agent actually produced fresh output.

## True-Fix Criteria (Required)

A stale-agent alert should only be marked "fixed" when:

1. Agent output timestamp is refreshed (newer than alert time)
2. Output file/table contains new data (not just re-logged old data)
3. Freshness age drops below threshold
4. Next scheduled health check passes without re-triggering
5. Alert is suppressed only AFTER verified freshness, not before

## Design

```
IF escalation marks "fixed":
    CHECK agent_output_timestamp > alert_timestamp
    CHECK output_row_count_delta > 0 OR output_file_mtime > alert_time
    IF both true:
        status = "verified_fixed"
        suppress_alert = true
    ELSE:
        status = "analyzed_not_fixed"
        suppress_alert = false
        re_escalate = true
```

## Not Implemented in Phase 67

This is a design/audit doc. Implementation requires modification of the escalation loop script (future phase).
