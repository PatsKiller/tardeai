#!/usr/bin/env bash
# PR-5 — Post-sale redeploy cron: detect → recompute → monitor (trading days).
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
[ -x "$PY" ] || PY="python3"
MARKER="# BEGIN deploy-redeploy-cron"
END="# END deploy-redeploy-cron"
LOG="$PROJ/logs/deploy_redeploy_cron.log"

mkdir -p "$PROJ/logs"

LINES=(
  "10 10 * * 1-5 cd $PROJ && $PY scripts/deploy_detect.py --apply --trading-days-only --days 14 >> $LOG 2>&1"
  "15 10 * * 1-5 cd $PROJ && $PY scripts/deploy_recompute.py --apply --limit 100 >> $LOG 2>&1"
  "20 10 * * 1-5 cd $PROJ && $PY scripts/deploy_monitor.py --apply --limit 100 >> $LOG 2>&1"
)

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" \
  | grep -v 'deploy_detect.py --apply' \
  | grep -v 'deploy_recompute.py --apply' \
  | grep -v 'deploy_monitor.py --apply' > "$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  for ln in "${LINES[@]}"; do echo "$ln"; done
  echo "$END"
} | crontab -
rm -f "$TMP"

echo "Installed deploy-redeploy cron (PR-5):"
crontab -l | grep -A5 "$MARKER"