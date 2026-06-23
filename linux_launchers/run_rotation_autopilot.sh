#!/usr/bin/env bash
# Rotation autopilot — autonomous small-cap / trend-switch screening.
# Runs every 15 min during market hours; flock-guarded.
#
# Suggested crontab (PROJ/PY at top of crontab):
#   */15 4-16 * * 1-5 cd $PROJ && bash linux_launchers/run_rotation_autopilot.sh cron >> logs/rotation_autopilot.log 2>&1
set -euo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJ/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
TRIGGER="${1:-cron}"
LOCK="/tmp/tradeai_rotation_autopilot.lock"

cd "$PROJ"
exec flock -n "$LOCK" \
    bash "$PROJ/scripts/market_day_gate.sh" \
    "$PY" scripts/rotation_autopilot.py --tick --trigger "$TRIGGER"