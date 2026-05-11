# Phase 2 Early Install Freeze and Observation Runbook

## Summary

Session 36 Phase 2 cron was installed before three real scheduled Phase 1 cron runs had occurred. Validation passed and Phase 2 is analysis-only, but further migration is frozen until scheduled cron behavior is observed.

Phase 2 validation results (all prior to first scheduled run):
- 15/15 dry-run success
- 15/15 manual live success
- 15/15 cron-command test success
- Validation 16/16 PASS
- No broker, Telegram, config, or promotion changes

The gap: Phase 1 cron was installed on 2026-05-09. Phase 2 cron was installed the same day. Neither has had a real scheduled run yet. Scheduled runs begin 2026-05-10.

## Current Cron Blocks

- Session35 Phase 1:
  - 7:15 AM daily
  - system_facts
  - self_improvement_snapshot
  - self_improvement_component_health

- Session36 Phase 2:
  - 7:45 AM weekdays
  - 15 analysis-only stages
  - regime, learning, backtesting observation stages
  - no broker, no Telegram send, no config promotion

## Freeze Rule

No Session 37.
No Phase 3 cron migration.
No additional cron changes.
No expansion of pipeline cron.
No broker/config/Telegram/promotion stage migration.

Freeze remains until:

- 3 successful scheduled Phase 1 runs (7:15 AM daily)
- 3 successful scheduled Phase 2 runs (7:45 AM weekdays)
- No unsafe strings in logs
- No safety drift
- No unexpected DB growth
- No operator confusion

## Daily Observation Commands

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

# Check cron logs
tail -100 logs/cron_phase1_observability.log
tail -100 logs/cron_phase2_observability.log

# Scan for unsafe strings
grep -iE "alpaca|submit_order|place_order|execute-ready|broker order|cancel_order|replace_order|close_position|telegram send|approve implementation|promote challenger|live trading" logs/cron_phase1_observability.log logs/cron_phase2_observability.log || true

# Safety gate
.venv/bin/python scripts/live_trading_gate.py --assert-safe

# Holdings integrity
python3 -c "import json; d=json.load(open('data/portfolios/state/holdings.json')); v=d['portfolio_totals']['total_value']; assert v>1_000_000, 'WIPED'; print(f'Holdings OK: \${v:,.0f}')"
```

## Observation Timeline

| Date       | Day | Phase 1 (7:15 AM) | Phase 2 (7:45 AM) | Notes                |
|------------|-----|--------------------|--------------------|----------------------|
| 2026-05-10 | Sat | Run 1              | — (weekdays only)  | First scheduled run  |
| 2026-05-11 | Sun | Run 2              | — (weekdays only)  |                      |
| 2026-05-12 | Mon | Run 3              | Run 1              | First Phase 2 run    |
| 2026-05-13 | Tue | Run 4              | Run 2              |                      |
| 2026-05-14 | Wed | Run 5              | Run 3              | Freeze can lift      |

Earliest freeze-lift date: **2026-05-14** (after 3 Phase 1 + 3 Phase 2 scheduled runs).

## What to Do If Something Fails

1. Check the log for the failed stage
2. Run `scripts/live_trading_gate.py --assert-safe` — confirm still safe
3. Check holdings value — confirm above $1M
4. Do NOT modify crontab, code, or configs
5. Document the failure in this file
6. If safety has failed (broker calls, live trading enabled, holdings wiped): disable cron immediately

## Incident Log

| Date | Phase | Observation | Action Taken |
|------|-------|-------------|--------------|
|      |       |             |              |
