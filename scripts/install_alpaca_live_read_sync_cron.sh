#!/usr/bin/env bash
# Install alpaca_live_read_sync cron (read-only data path).
# Safe to re-run — replaces only the marked block.
#
# Behavior: every 15 min market hours Mon–Fri. Script itself makes ZERO API calls
# when no live account has api_read_enabled=true (default R4 scaffolds).
# Does NOT enable is_enabled / api_write / live_arm.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
MARKER="# BEGIN alpaca-live-read-sync-cron"
END="# END alpaca-live-read-sync-cron"
PY="$PROJ/.venv/bin/python"
LINE='*/15 9-16 * * 1-5 cd '"$PROJ"' && bash '"$PROJ"'/scripts/safe_flock.sh /tmp/alpaca_live_read_sync.lock '"$PY"' scripts/alpaca_live_read_sync.py >> '"$PROJ"'/logs/alpaca_live_read_sync.log 2>&1'

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" | grep -v 'alpaca_live_read_sync' > "$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  echo "$LINE"
  echo "$END"
} | crontab -
rm -f "$TMP"
echo "Installed Alpaca live read-sync cron:"
echo "  - every 15 min, market hours Mon–Fri (9–16 ET wall clock)"
echo "  - no-op until api_read_enabled=true on a live alpaca account"
crontab -l | grep -A2 "$MARKER" || true
