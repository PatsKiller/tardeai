#!/usr/bin/env bash
# Phase 9C: Scheduled maturity board + phase readiness reports. Read-only.
set -euo pipefail

PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/maturity_control_board.log"
LOCK="/tmp/tradeai_maturity_control_board.lock"
TS=$(date '+%Y-%m-%d %H:%M:%S')

log() { echo "$TS [maturity-board] $*" >> "$LOG"; echo "$TS [maturity-board] $*"; }

ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }

HOLDINGS_OK=$($PY -c 'import sys; sys.path[:0]=["'"$PROJ"'/scripts","'"$PROJ"'/scripts/lib"]; from holdings_sanity import file_is_intact; print("OK" if file_is_intact("'"$PROJ"'/data/portfolios/state/holdings.json") else "FAIL")' 2>/dev/null || echo "FAIL")
[ "$HOLDINGS_OK" != "OK" ] && { log "ABORT: holdings guard failed"; exit 1; }

log "Starting"
exec {fd}>"$LOCK" && flock -n "$fd" || { log "Locked, skipping"; $PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('maturity_control_board','Governance','skipped',datetime.now(timezone.utc),datetime.now(timezone.utc),source='cron_flock_blocked')" 2>/dev/null || true; exit 0; }
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
mkdir -p "$PROJ/docs/maturity_hardening"
set +e
$PY "$PROJ/scripts/report_maturity_control_board.py" --output-json "$PROJ/docs/maturity_hardening/maturity_control_board_latest.json" --output-md "$PROJ/docs/maturity_hardening/maturity_control_board_latest.md" --verbose 2>&1 | while IFS= read -r line; do log "$line"; done
$PY "$PROJ/scripts/report_phase_readiness_gates.py" --output-json "$PROJ/docs/maturity_hardening/phase_readiness_latest.json" --output-md "$PROJ/docs/maturity_hardening/phase_readiness_latest.md" --verbose 2>&1 | while IFS= read -r line; do log "$line"; done
_EXIT=$?; set -e
_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('maturity_control_board','Governance','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true
log "Finished"
