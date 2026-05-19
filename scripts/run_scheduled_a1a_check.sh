#!/usr/bin/env bash
# GOV-1: Scheduled A1A compliance check. Read-only.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/governance_a1a_check.log"
LOCK="/tmp/tradeai_a1a_check.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [a1a-check] $*" >> "$LOG"; echo "$TS [a1a-check] $*"; }

ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

HOLDINGS_OK=$($PY -c 'import json; d=json.load(open("'"$PROJ"'/data/portfolios/state/holdings.json")); print("OK" if d["portfolio_totals"]["total_value"] > 1000000 else "FAIL")' 2>/dev/null || echo "FAIL")
[ "$HOLDINGS_OK" != "OK" ] && { log "ABORT: holdings guard failed"; exit 1; }

log "Starting"
exec {fd}>"$LOCK" && flock -n "$fd" || { log "Locked, skipping"; exit 0; }

mkdir -p "$PROJ/docs/governance"
$PY "$PROJ/scripts/check_a1a_compliance.py" --last-commit \
  --output-json "$PROJ/docs/governance/a1a_latest_check_results.json" \
  --output-md "$PROJ/docs/governance/a1a_latest_check_report.md" \
  --verbose 2>&1 | while IFS= read -r line; do log "$line"; done

log "Finished"
