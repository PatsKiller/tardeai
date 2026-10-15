#!/usr/bin/env bash
# Options monitor — proposals + open-position refresh (market hours).
# Day pull: every 5 min 11:00–15:55 ET weekdays, plus the 16:05 close.
# 9:30–11:00 stays empty so this does not share the scalp GPU window.
# Overnight there is no chain cron. A non-force read outside the regular
# session serves the last snapshot (proposal_cache_serves).
# n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
# ratified): --dry-run is OFFLINE and wins over every live argument. It runs before any cd, .env source, lock,
# interpreter or broker call, makes NO broker call (not even a read) and writes nothing; it prints the plan and one
# LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run_requires_broker_read). Bash builtins only.
# Proof: tests/test_onboard_f09_b5_20261015.py.
if [[ " $* " == *" --dry-run "* ]]; then
    _f09_lane="run-options-monitor"
    printf 'DRY-RUN %s: would %s; argv=%s; dry-run wins over live arguments; broker read required to plan: nothing done; nothing read, no broker call, no send, no file write\n' \
        "$_f09_lane" "pull option chains and refresh options proposals and open-position marks" "$*"
    TZ=UTC printf 'LANE_OUTPUT {"attempted_count": 0, "emitted_at": "%(%Y-%m-%dT%H:%M:%S+00:00)T", "empty_reason": "%s", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "started_at": null, "unit": "%s"}\n' \
        -1 "dry_run_requires_broker_read" "$_f09_lane" "$$" "options proposals and positions refreshed" >&2
    exit 0
fi

set -euo pipefail
PROJECT_ROOT="${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJECT_ROOT"
set -a
source "$PROJECT_ROOT/.env" 2>/dev/null || true
set +a
exec bash scripts/safe_flock.sh /tmp/tradeai_options_monitor.lock \
  .venv/bin/python scripts/run_options_monitor.py >> logs/options_monitor.log 2>&1