#!/usr/bin/env bash
# Daily TradeInView annotation Telegram nudge (weekdays 18:30 ET = 23:30 UTC standard / adjust for DST manually if needed)
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
MARKER="# BEGIN tradeinview-annotation-cron"
END="# END tradeinview-annotation-cron"
LINE1="30 23 * * 1-5 cd $PROJ && $PY scripts/journal_annotation_reminder.py >> $PROJ/logs/journal_annotation_reminder.log 2>&1"
LINE2="0 12 * * 1-5 cd $PROJ && $PY scripts/journal_tilt_morning_hook.py >> $PROJ/logs/journal_tilt_hook.log 2>&1"

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" \
  | grep -v 'journal_annotation_reminder.py' \
  | grep -v 'journal_tilt_morning_hook.py' > "$TMP" || true
{ cat "$TMP"; echo "$MARKER"; echo "$LINE1"; echo "$LINE2"; echo "$END"; } | crontab -
rm -f "$TMP"
echo "Installed TradeInView annotation cron:"
crontab -l | grep -A2 "$MARKER"