#!/usr/bin/env bash
# PIPE-OBS-1: Wrap a command with pipeline_runs telemetry. No trades. No orders.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
set -a; source "$PROJ/.env"; set +a
PY="$PROJ/.venv/bin/python"

STAGE="unknown"
CATEGORY="unknown"
SOURCE="cron"
CMD_ARGS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --stage) shift; STAGE="${1:-unknown}" ;;
    --category) shift; CATEGORY="${1:-unknown}" ;;
    --source) shift; SOURCE="${1:-cron}" ;;
    --) shift; CMD_ARGS=("$@"); break ;;
    *) CMD_ARGS+=("$1") ;;
  esac
  shift || true
done

[ "${#CMD_ARGS[@]}" -eq 0 ] && { echo "Usage: $0 --stage NAME --category CAT -- command..."; exit 1; }

STARTED=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)

# Run command
set +e
"${CMD_ARGS[@]}"
EXIT_CODE=$?
set -e

FINISHED=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
STATUS="success"
[ $EXIT_CODE -ne 0 ] && STATUS="failed"

# Record telemetry
$PY -c "
import sys; sys.path.insert(0, '$PROJ/scripts')
from pipeline_run_telemetry import record_stage_run
from datetime import datetime, timezone
record_stage_run(
    stage_name='$STAGE', category='$CATEGORY', status='$STATUS',
    started_at=datetime.fromisoformat('$STARTED'),
    finished_at=datetime.fromisoformat('$FINISHED'),
    source='$SOURCE'
)
" 2>/dev/null || true

exit $EXIT_CODE
