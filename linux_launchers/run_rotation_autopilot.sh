#!/usr/bin/env bash
# Rotation autopilot — autonomous small-cap / trend-switch screening.
# Runs every 15 min during market hours; flock-guarded.
#
# Suggested crontab (PROJ/PY at top of crontab):
#   */15 4-16 * * 1-5 cd $PROJ && bash linux_launchers/run_rotation_autopilot.sh cron >> logs/rotation_autopilot.log 2>&1
# n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
# ratified): --dry-run is OFFLINE and wins over every live argument. It runs before any cd, .env source, lock,
# interpreter or broker call, makes NO broker call (not even a read) and writes nothing; it prints the plan and one
# LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run). Bash builtins only.
# Proof: tests/test_onboard_f09_b6_20261015.py.
if [[ " $* " == *" --dry-run "* ]]; then
    _f09_lane="rotation-autopilot"
    printf 'DRY-RUN %s: would %s; argv=%s; dry-run wins over live arguments; offline plan only; nothing read, no broker call, no send, no file write\n' \
        "$_f09_lane" "evaluate IWM/SPY rotation state and, on a regime switch, run the small-cap bridge and auto_proposal_generator (proposal handoff; order path in static reach) and alert once" "$*"
    TZ=UTC printf 'LANE_OUTPUT {"attempted_count": 0, "emitted_at": "%(%Y-%m-%dT%H:%M:%S+00:00)T", "empty_reason": "%s", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "started_at": null, "unit": "%s"}\n' \
        -1 "dry_run" "$_f09_lane" "$$" "rotation ticks evaluated" >&2
    exit 0
fi

set -euo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
. "$PROJ/scripts/lib/venv_python.sh"; PY="$(tradeai_venv_python "$PROJ")"  # release dirs ship no .venv
TRIGGER="${1:-cron}"
LOCK="/tmp/tradeai_rotation_autopilot.lock"

cd "$PROJ"
exec flock -n "$LOCK" \
    bash "$PROJ/scripts/market_day_gate.sh" \
    "$PY" scripts/rotation_autopilot.py --tick --trigger "$TRIGGER"