# Stop Management V2.2 — Monitor Merge

**Phase:** STOP-V2.2
**Date:** 2026-05-22
**Purpose:** Eliminate racing stop monitors by merging into unified supervisor

## Problem
Two monitors raced:
- `open_trade_monitor.py` (*/2): stop hits, time stops, news, alerts, trailing
- `paper_trade_monitor.py` (*/5): trailing, phantom detection, stop replacement

Both could adjust the same stop order simultaneously, causing conflicts.

## Solution
`unified_stop_supervisor.py` runs every 3 minutes:
1. STOP-V2.1 broker reconciliation (always)
2. open_trade_monitor logic (market hours only)
3. paper_trade_monitor logic (market hours only)
After hours: reconciliation and alerts only, no trailing.

## Cron Changes
- `open_trade_monitor */2` → commented out
- `paper_trade_monitor */5` → commented out
- `unified_stop_supervisor */3` → installed
- Rollback: `bash scripts/rollback_stop_v22_monitor_merge.sh --apply`

## What Was NOT Done
- No stop orders created, canceled, or moved
- No new trailing tiers (deferred to V2.3)
- No ATM mode changes
