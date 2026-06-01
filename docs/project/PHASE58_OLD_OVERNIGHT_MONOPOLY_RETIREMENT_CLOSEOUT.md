# Phase 58 — Old Overnight Monopoly Retirement Closeout

**Date:** 2026-06-01
**Status:** DESIGN ONLY — not applied (operator approval required)

## Old Monopoly Path

| Item | Value |
|------|-------|
| Script | scripts/overnight_batch.py |
| Timer/cron | Nightly cron |
| Model | gemma3:12b |
| Risk | Owns entire overnight window |
| Replacement | high_llm_job_queue with quota |

## Retirement Plan

1. Run 3-night parallel comparison (old + new queue dry-runs)
2. Validate no missed jobs
3. Disable old cron line (tag PHASE58-MIGRATED)
4. Enable global queue execution (Phase 60)
5. Monitor for 7 days

## Not Applied

Requires explicit operator approval:
"Approve Phase 58F — disable old overnight monopoly after queue validation."

## Current State

Old overnight process remains active. Global queue has all jobs represented but does not execute them yet.
