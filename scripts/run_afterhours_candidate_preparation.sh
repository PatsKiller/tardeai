#!/usr/bin/env bash
# AFTERHOURS-READY-1: After-hours candidate preparation. No trades. No orders.
#
# Refactor wave 2 (cron -> n8n, 2026-10-10, cron:L196):
#   - PROJ is the tree this script is served from (the CURRENT release under cron), not the dev
#     checkout: the cron line `cd`s into CURRENT and then ran dev-tree code. Release dirs ship no
#     .venv, so PY is TRADEAI_VENV_PYTHON, else PROJ/.venv, else the canonical dev venv (the
#     lib.live_project_root.venv_python order). logs/ resolves through the release's
#     persistent-state symlink.
#   - the python step's exit code is propagated (the `| while read` pipe made $? always 0).
#   - --dry-run: the python step runs with --dry-run instead of --apply (READ ONLY session, no
#     INSERT, no receipt) and this wrapper appends nothing to the log file and records no pipeline
#     telemetry (AGENTS.md §6).
set -euo pipefail
DRY_RUN=0
for _a in "$@"; do [ "$_a" = "--dry-run" ] && DRY_RUN=1; done
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
set -a; source "$PROJ/.env"; set +a
if [ -n "${TRADEAI_VENV_PYTHON:-}" ] && [ -x "${TRADEAI_VENV_PYTHON}" ]; then
  PY="$TRADEAI_VENV_PYTHON"
elif [ -x "$PROJ/.venv/bin/python" ]; then
  PY="$PROJ/.venv/bin/python"
else
  PY="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python"
fi
LOG="$PROJ/logs/afterhours_candidate_preparation.log"
TS=$(date '+%Y-%m-%d %H:%M:%S')
log() {
  if [ "$DRY_RUN" = "1" ]; then echo "$TS [afterhours] [dry-run] $*"; return 0; fi
  echo "$TS [afterhours] $*" >> "$LOG"; echo "$TS [afterhours] $*"
}
ALPACA_MODE=$(grep '^ALPACA_MODE=' "$PROJ/.env" | cut -d= -f2-)
LLM_DISABLE=$(grep '^LLM_DISABLE_LIVE_EXECUTION=' "$PROJ/.env" | cut -d= -f2-)
[ "$ALPACA_MODE" != "paper" ] && { log "ABORT: ALPACA_MODE=$ALPACA_MODE"; exit 1; }
[ "$LLM_DISABLE" != "true" ] && { log "ABORT: LLM_DISABLE=$LLM_DISABLE"; exit 1; }
DOW=$(date +%u); [ "$DOW" -gt 5 ] && { log "SKIP: weekend"; exit 0; }
MODE_ARG="--apply"; [ "$DRY_RUN" = "1" ] && MODE_ARG="--dry-run"
log "Starting after-hours candidate preparation"
_TELEM_START=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
set +e
"$PY" "$PROJ/scripts/run_afterhours_candidate_preparation.py" --session after_close --date today --run-strategy-fit --prepare-candidates "$MODE_ARG" 2>&1 | while IFS= read -r line; do log "$line"; done
_EXIT=${PIPESTATUS[0]}; set -e
if [ "$DRY_RUN" = "1" ]; then log "Finished (exit=$_EXIT)"; exit "$_EXIT"; fi
_TELEM_STATUS="success"; [ $_EXIT -ne 0 ] && _TELEM_STATUS="failed"
"$PY" -c "import sys; sys.path.insert(0,'$PROJ/scripts'); from pipeline_run_telemetry import record_stage_run; from datetime import datetime,timezone; record_stage_run('afterhours_candidate_prep','Proposal Pipeline','$_TELEM_STATUS',datetime.fromisoformat('$_TELEM_START'),datetime.now(timezone.utc),source='cron')" 2>/dev/null || true
log "Finished (exit=$_EXIT)"
exit "$_EXIT"
