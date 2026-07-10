#!/usr/bin/env bash
# Weekly Ross vs TradeAI alignment audit — Mon 8:30 AM ET (13:30 UTC standard / 12:30 EDT)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
python3 scripts/warrior_weekly_audit_cron.py --days 7 >> logs/warrior_weekly_audit.log 2>&1