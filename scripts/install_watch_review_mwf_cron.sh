#!/usr/bin/env bash
# Install Mon/Wed/Fri Maria 16:05 + CIO 16:20 ET cron for watch review workers.
# Idempotent: replaces the TRADEAI_WATCH_REVIEW_MWF block only.
set -euo pipefail

WT="${WATCH_REVIEW_WT:-/home/johnclaw/tradeai-wt-watch-review-automation}"
MAIN="${TRADEAI_MAIN:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
PY="${WATCH_REVIEW_PY:-$MAIN/.venv/bin/python}"
RUNTIME="${TRADEAI_RUNTIME_ROOT:-$MAIN/data/runtime}"
LOG_DIR="$WT/logs"
mkdir -p "$LOG_DIR"

if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
if [[ ! -f "$WT/scripts/run_watch_review_workers.py" ]]; then
  echo "missing $WT/scripts/run_watch_review_workers.py" >&2
  exit 1
fi

BLOCK_BEGIN="# BEGIN TRADEAI_WATCH_REVIEW_MWF"
BLOCK_END="# END TRADEAI_WATCH_REVIEW_MWF"

NEW_BLOCK=$(cat <<EOF
$BLOCK_BEGIN
# Maria flash narrative — Mon/Wed/Fri 16:05 America/New_York (host TZ is ET)
5 16 * * 1,3,5 cd $WT && TRADEAI_RUNTIME_ROOT=$RUNTIME PYTHONPATH=scripts flock -n -E 99 /tmp/tradeai_watch_review_maria.lock timeout 45m $PY scripts/run_watch_review_workers.py --mode execute --allow-execute --role maria >> $LOG_DIR/watch_review_maria.log 2>&1; rc=\$?; [ \$rc -eq 99 ] && echo "\$(date +\\%Y-\\%m-\\%d\\ \\%H:\\%M:\\%S) [flock] maria skipped" >> $LOG_DIR/watch_review_maria.log
# CIO pro synthesis — Mon/Wed/Fri 16:20 ET (requires Maria COMPLETE where planned)
20 16 * * 1,3,5 cd $WT && TRADEAI_RUNTIME_ROOT=$RUNTIME PYTHONPATH=scripts flock -n -E 99 /tmp/tradeai_watch_review_cio.lock timeout 45m $PY scripts/run_watch_review_workers.py --mode execute --allow-execute --role cio >> $LOG_DIR/watch_review_cio.log 2>&1; rc=\$?; [ \$rc -eq 99 ] && echo "\$(date +\\%Y-\\%m-\\%d\\ \\%H:\\%M:\\%S) [flock] cio skipped" >> $LOG_DIR/watch_review_cio.log
$BLOCK_END
EOF
)

TMP=$(mktemp)
crontab -l 2>/dev/null | sed "/$BLOCK_BEGIN/,/$BLOCK_END/d" > "$TMP" || true
# ensure trailing newline
printf '%s\n' "$(cat "$TMP")" > "$TMP"
echo "$NEW_BLOCK" >> "$TMP"
crontab "$TMP"
rm -f "$TMP"
echo "Installed TRADEAI_WATCH_REVIEW_MWF cron:"
crontab -l | sed -n "/$BLOCK_BEGIN/,/$BLOCK_END/p"
echo "workers still need: $PY $WT/scripts/run_watch_review_workers.py --mode enable-workers"
