#!/usr/bin/env bash
# PR4 — Install options paper lifecycle monitor + Alpaca options reconcile cron.
# Safe to re-run: replaces only the marked block.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
MARKER="# BEGIN options-paper-lifecycle-cron"
END="# END options-paper-lifecycle-cron"

# Job lines only — no free-form comment lines inside the block (some cron builds
# mis-parse "# word ..." as a schedule when stdin/newline glitches occur).
JOB_LINES=(
  "35,45,55 9 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_monitor.sh"
  "*/10 10-15 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_monitor.sh"
  "5 16 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_monitor.sh"
  "0 10-15 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/reconcile_alpaca_paper_options.sh"
  "10 17 * * 1-5 cd $PROJ && bash $PROJ/linux_launchers/run_options_paper_position_monitor.sh"
)

TMP=$(mktemp)
OUT=$(mktemp)
trap 'rm -f "$TMP" "$OUT"' EXIT

# Strip prior installs of this block and standalone launcher lines.
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" \
  | grep -v 'linux_launchers/run_options_monitor.sh' \
  | grep -v 'linux_launchers/run_options_paper_position_monitor.sh' \
  | grep -v 'linux_launchers/reconcile_alpaca_paper_options.sh' \
  > "$TMP" || true

# Guarantee trailing newline so the next block cannot glue to the last job line.
printf '%s\n' "$(cat "$TMP")" > "$OUT"
mv "$OUT" "$TMP"

{
  cat "$TMP"
  printf '%s\n' "$MARKER"
  for ln in "${JOB_LINES[@]}"; do printf '%s\n' "$ln"; done
  printf '%s\n' "$END"
} > "$OUT"

# Validate before install (cronie/GNU cron); fall back to direct install.
if crontab -T "$OUT" >/dev/null 2>&1; then
  crontab "$OUT"
elif crontab "$OUT" 2>/dev/null; then
  :
else
  echo "REFUSED: generated crontab failed validation. Inspect: $OUT" >&2
  echo "First lines around the new block:" >&2
  grep -n -A6 -B2 "$MARKER" "$OUT" >&2 || tail -20 "$OUT" >&2
  exit 1
fi

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
crontab -l | grep -A8 "$MARKER"