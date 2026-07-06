#!/usr/bin/env bash
# PR4 — Install options paper lifecycle monitor + Alpaca options reconcile cron.
# Safe to re-run: replaces only the marked block.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
MARKER="# BEGIN options-paper-lifecycle-cron"
END="# END options-paper-lifecycle-cron"

LINES=(
  "# Options desk pipeline (proposals + Schwab legs + lifecycle hook via run_options_monitor.py)"
  "35,45,55 9 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_monitor.sh"
  "*/10 10-15 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_monitor.sh"
  "5 16 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_monitor.sh"
  "# Alpaca paper options reconcile (hourly market hours — fills/closes → monitored registry)"
  "0 10-15 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/reconcile_alpaca_paper_options.sh"
  "# After-hours lifecycle snapshot (advisory marks when after_hours_snapshot enabled)"
  "10 17 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_paper_position_monitor.sh"
)

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" \
  | grep -v 'linux_launchers/run_options_monitor.sh' \
  | grep -v 'linux_launchers/run_options_paper_position_monitor.sh' \
  | grep -v 'linux_launchers/reconcile_alpaca_paper_options.sh' \
  > "$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  for ln in "${LINES[@]}"; do echo "$ln"; done
  echo "$END"
} | crontab -
rm -f "$TMP"

chmod +x "$PROJ/linux_launchers/run_options_paper_position_monitor.sh" \
         "$PROJ/linux_launchers/reconcile_alpaca_paper_options.sh" \
         "$PROJ/linux_launchers/run_options_monitor.sh" 2>/dev/null || true

MIG="$PROJ/migrations/2026_07_07_options_monitored_positions.sql"
if command -v psql >/dev/null 2>&1 && [[ -f "$PROJ/.env" ]]; then
  echo "Applying migration (idempotent) if DB reachable: $MIG"
  set -a; source "$PROJ/.env"; set +a
  if [[ -n "${DATABASE_URL:-}" ]]; then
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$MIG" && echo "Migration applied." \
      || echo "WARN: migration apply failed — run manually when DB is up."
  else
    echo "SKIP: DATABASE_URL not set — apply $MIG manually."
  fi
else
  echo "NOTE: apply $MIG manually if tables are missing."
fi

echo "Installed options paper lifecycle cron:"
crontab -l | grep -A12 "$MARKER"