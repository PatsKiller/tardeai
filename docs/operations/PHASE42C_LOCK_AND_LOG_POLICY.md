# Phase 42C — Lock and Log Policy

**Date:** 2026-06-01
**Status:** DESIGN ONLY

## Lock Policy

- Single lock: /tmp/screener_pipeline.lock
- flock -n (non-blocking) — skip if already running
- Replaces: /tmp/finviz_screener.lock + /tmp/screener_pm.lock

## Log Policy

- Single log: logs/screener_pipeline.log
- Append mode with timestamps
- Replaces: logs/finviz_screener.log + logs/screener_pm.log
- Rotation: logrotate or built-in (future)
