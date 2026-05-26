# Source Export: scripts/run_closed_trade_digest_cron.sh

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/run_closed_trade_digest_cron.sh` |
| **Git Branch** | `main` |
| **Git Commit** | `915876f` |
| **Export Timestamp** | `2026-05-26T19:48:00Z` |
| **SHA256** | `515d0bbd404892e53cdab971a0601a79d13d023c688927260ced165b9987f575` |
| **File Size** | 1615 bytes |

## Full Source

```sh
#!/usr/bin/env bash
# JOURNAL-UX-2B: Closed trade digest cron wrapper. No trades. No orders.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"
LOG="$PROJ/logs/closed_trade_digest_cron.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
log() { echo "$TS [digest] $*" >> "$LOG"; echo "$TS [digest] $*"; }
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }
DOW=$(date +%u); [ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }

MODE="${1:---send}"
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
set +e
if [ "$MODE" = "--dry-run" ]; then
  log "Starting dry-run"
  $PY "$PROJ/scripts/send_closed_trade_digest.py" --date today --dry-run 2>&1 | while IFS= read -r line; do log "$line"; done
else
  log "Starting production send"
  $PY "$PROJ/scripts/send_closed_trade_digest.py" --date today --send 2>&1 | while IFS= read -r line; do log "$line"; done
fi
_EXIT=$?; set -e
_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
$PY -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('closed_trade_digest','Intelligence','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true
log "Finished"
```
