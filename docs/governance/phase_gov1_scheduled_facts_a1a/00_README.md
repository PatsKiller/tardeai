# GOV-1 — Scheduled System Facts and A1A Checks

**Status:** COMPLETE

## Schedule

| Time (ET) | Day | Job |
|-----------|-----|-----|
| 07:40 | M-F | System facts generation |
| 07:45 | M-F | A1A compliance check |
| 07:50 | M-F | Governance status report |
| 18:00 | Sun | System facts generation |
| 18:05 | Sun | A1A compliance check |
| 18:10 | Sun | Governance status report |

## Commands

```bash
# Manual run
scripts/run_scheduled_system_facts.sh
scripts/run_scheduled_a1a_check.sh
.venv/bin/python scripts/report_governance_status.py --verbose

# Check cron
crontab -l | sed -n '/BEGIN GOV-1/,/END GOV-1/p'

# Rollback
scripts/rollback_gov1_governance_cron.sh --apply
```

## Safety

- All scripts verify ALPACA_MODE=paper + LLM_DISABLE=true + holdings > $1M
- Read-only: no trading, no strategy activation, no order submission
- Rollback removes only GOV-1 cron entries
