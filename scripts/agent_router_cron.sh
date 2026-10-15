#!/usr/bin/env bash
# n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
# ratified): --dry-run is OFFLINE and wins over every live argument. It runs before any cd, .env source, lock,
# interpreter or broker call, makes NO broker call (not even a read) and writes nothing; it prints the plan and one
# LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run). Bash builtins only.
# Proof: tests/test_onboard_f09_b6_20261015.py.
if [[ " $* " == *" --dry-run "* ]]; then
    _f09_mode=light
    for _f09_a in "$@"; do [[ "$_f09_a" != --dry-run ]] && { _f09_mode="$_f09_a"; break; }; done
    _f09_lane="agent-router-cron-${_f09_mode}"
    printf 'DRY-RUN %s: would %s; argv=%s; dry-run wins over live arguments; offline plan only; nothing read, no broker call, no send, no file write\n' \
        "$_f09_lane" "refresh the agent context (refresh_agent_context.py --mode ${_f09_mode}) and append its JSON to the mode log" "$*"
    TZ=UTC printf 'LANE_OUTPUT {"attempted_count": 0, "emitted_at": "%(%Y-%m-%dT%H:%M:%S+00:00)T", "empty_reason": "%s", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "started_at": null, "unit": "%s"}\n' \
        -1 "dry_run" "$_f09_lane" "$$" "agent context refreshed" >&2
    exit 0
fi

set -euo pipefail
cd /home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
mkdir -p logs
MODE="${1:-light}"
.venv/bin/python scripts/refresh_agent_context.py --mode "$MODE" --json >> "logs/agent_context_${MODE}.log" 2>&1 || true
