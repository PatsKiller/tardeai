# Phase 6E Scope — Scheduled Stale Proposal Sweeper

**Date:** 2026-05-15

## 1. Purpose

Operationalize the Phase 6D stale proposal sweeper with a safe scheduled wrapper so pending proposals are kept fresh without manual runs.

Phase 6E schedules stale proposal hygiene only. It does not approve proposals, create trades, submit orders, or bypass approval safety gates.

## 2. Schedule

| Time (ET) | Mode | Day | Purpose |
|-----------|------|-----|---------|
| 08:15 | dry-run | Mon-Fri | Pre-market freshness report |
| 08:25 | apply | Mon-Fri | Mark stale proposals before market open |
| 16:10 | report-only | Mon-Fri | End-of-day summary |

## 3. Safety

- Wrapper uses flock to prevent overlap
- Verifies ALPACA_MODE=paper before running
- Dry-run is the default (no args = dry-run)
- Apply requires explicit --apply
- Never deletes, approves, or submits
- Rollback script can remove cron entries

## 4. Rollback

```bash
./scripts/rollback_phase6e_stale_sweeper_cron.sh --apply
```
