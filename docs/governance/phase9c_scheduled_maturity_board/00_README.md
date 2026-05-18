# Phase 9C — Scheduled Maturity Control Board

**Status:** COMPLETE

## Schedule

| Time (ET) | Day | Job |
|-----------|-----|-----|
| 07:55 | M-F | Maturity control board + phase readiness gates |
| 08:00 | M-F | Operator readiness summary |
| 18:15 | Sun | Maturity control board + phase readiness gates |
| 18:20 | Sun | Operator readiness summary |

## Commands

```bash
# Manual run
bash scripts/run_scheduled_maturity_control_board.sh
.venv/bin/python scripts/report_operator_readiness_summary.py --verbose

# Check cron
crontab -l | sed -n '/BEGIN Phase 9C/,/END Phase 9C/p'

# Rollback
scripts/rollback_phase9c_maturity_cron.sh --apply
```

## Outputs

- `docs/maturity_hardening/maturity_control_board_latest.json` / `.md`
- `docs/maturity_hardening/phase_readiness_latest.json` / `.md`
- `docs/maturity_hardening/operator_readiness_latest.json` / `.md`

## Safety

- Wrapper verifies ALPACA_MODE=paper + LLM_DISABLE=true + holdings > $1M
- Read-only: no trading, no strategy activation, no order submission
- Rollback removes only Phase 9C cron entries
- Does not source .env (reads individual values only)
- Uses flock to prevent concurrent runs
