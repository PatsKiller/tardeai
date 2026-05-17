# Phase 2 Early Install Freeze and Observation Runbook

**Status:** Active observation runbook
**Updated:** 2026-05-16

## Current Status

Phase 2 cron was installed early, before the original observation threshold had been reached. The system is still paper-safe, and no code, SQL, crontab, `.env`, holdings, or live-trading changes are part of this review.

Observed scheduled runs so far:
- Phase 1 cron: 2 scheduled runs observed
- Phase 2 cron: 1 scheduled run observed

That is not enough to lift the freeze yet.

## Freeze Rule

Keep the freeze in place until:
- 3 successful scheduled Phase 1 runs are observed
- 3 successful scheduled Phase 2 runs are observed
- no unsafe strings appear in the cron logs
- safety checks remain green
- no unexpected holdings or live-trading drift appears

Do not advance to the next phase until the threshold is met.

## Current Cron Blocks

- Phase 1 cron, 7:15 AM daily
  - `system_facts`
  - `self_improvement_snapshot`
  - `self_improvement_component_health`

- Phase 2 cron, 7:45 AM weekdays
  - 15 analysis-only stages
  - no broker actions
  - no Telegram live sends
  - no config promotion
  - no strategy/source/screener mutations

## Daily Observation Commands

```bash
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

tail -100 logs/cron_phase1_observability.log
tail -100 logs/cron_phase2_observability.log

grep -iE "alpaca|submit_order|place_order|execute-ready|broker order|cancel_order|replace_order|close_position|telegram send|approve implementation|promote challenger|live trading" \
  logs/cron_phase1_observability.log logs/cron_phase2_observability.log || true

.venv/bin/python scripts/live_trading_gate.py --assert-safe

python3 - <<'PY'
import json
from pathlib import Path
p = Path('data/portfolios/state/holdings.json')
d = json.loads(p.read_text())
print(f"Holdings OK: ${d['portfolio_totals']['total_value']:,.0f}")
PY
```

## If Something Fails

1. Check the failing stage in the log.
2. Re-run the safety gate.
3. Confirm holdings are still above the expected threshold.
4. Do not edit code, SQL, crontab, `.env`, or holdings unless rollback is required.
5. Document the failure here.

## Next Operational Read

`docs/project/PHASE2_EARLY_INSTALL_FREEZE_AND_OBSERVATION_RUNBOOK.md`
