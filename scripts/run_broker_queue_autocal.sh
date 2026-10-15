#!/usr/bin/env bash
# Auto-recalibrate live broker queue: Schwab batch quotes -> paper_trade_proposals DB.
# n8n onboarding F09 (operator N8N Cutover Decision 2026-10-15; staged under AGENTS.md §23.14 until 12.0.0 is
# ratified): --dry-run is OFFLINE and wins over every live argument. It runs before any cd, .env source, lock,
# interpreter or broker call, makes NO broker call (not even a read) and writes nothing; it prints the plan and one
# LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run_requires_broker_read). Bash builtins only.
# Proof: tests/test_onboard_f09_b6_20261015.py.
if [[ " $* " == *" --dry-run "* ]]; then
    _f09_lane="run-broker-queue-autocal"
    printf 'DRY-RUN %s: would %s; argv=%s; dry-run wins over live arguments; broker read required to plan: nothing done; nothing read, no broker call, no send, no file write\n' \
        "$_f09_lane" "read Schwab batch quotes and recalibrate the live broker queue in paper_trade_proposals (broker_proposal_autocal.py --apply --force)" "$*"
    TZ=UTC printf 'LANE_OUTPUT {"attempted_count": 0, "emitted_at": "%(%Y-%m-%dT%H:%M:%S+00:00)T", "empty_reason": "%s", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "started_at": null, "unit": "%s"}\n' \
        -1 "dry_run_requires_broker_read" "$_f09_lane" "$$" "broker queue proposals recalibrated" >&2
    exit 0
fi

set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/broker_queue_autocal.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [broker-autocal] $*" >> "$LOG"; echo "$TS [broker-autocal] $*"; }

DOW=$(date +%u)
[ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }

log "Starting broker queue auto-recalibration"
$PY "$PROJ/scripts/broker_proposal_autocal.py" --apply --force 2>&1 | while IFS= read -r line; do log "$line"; done
log "Finished"