# Phase 42A — Market Scan Duplicate Selection

**Date:** 2026-06-01
**Status:** COMPLETE — design only

## Duplicate Scan Jobs (13 total)

### finviz_screener_runner.py (7 cron lines)
- 7:00, 8:00, 10:00, 12:00, 14:00, 16:00, 18:00 Mon-Fri
- All run the same script with `--run`
- Some use flock, some don't (inconsistent)

### trade_ai_orchestrator.py (6 cron lines)
- 9:00, 10:00, 12:00, 14:00, 16:00, 17:30 Mon-Fri
- All use safe_flock.sh with screener_pm.lock
- Different `--run-label` per slot
- 17:30 is the only one without `--no-llm`

## Proposed Pipeline: trade-ai-screener-pipeline

Merge 13 cron lines into 1 systemd timer with a controller script that:
1. Runs at configurable intervals (e.g., every 2 hours 7:00–18:00)
2. Executes finviz_screener_runner then trade_ai_orchestrator sequentially
3. Uses single flock
4. Passes run-label based on time
5. Skips on non-market days via market_day_gate.sh
