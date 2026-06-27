#!/usr/bin/env bash
# Install proposal lifecycle monitor + daily strategy audits. Safe to re-run.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
PY="$PROJ/.venv/bin/python"
MARKER="# BEGIN strategy-monitoring-cron"
END="# END strategy-monitoring-cron"

LINES=(
  "30 16 * * 1-5 cd $PROJ && $PY scripts/proposal_monitor.py --pending --apply >> $PROJ/logs/proposal_monitor.log 2>&1"
  "0 18 * * 1-5 cd $PROJ && $PY scripts/proposal_monitor.py --pending --apply >> $PROJ/logs/proposal_monitor.log 2>&1"
  "0 6 * * 1-5 cd $PROJ && $PY scripts/proposal_monitor.py --pending --apply >> $PROJ/logs/proposal_monitor.log 2>&1"
  "30 6 * * 1-5 cd $PROJ && $PY scripts/proposal_monitor.py --pending --apply >> $PROJ/logs/proposal_monitor.log 2>&1"
  "5 17 * * 1-5 cd $PROJ && bash $PROJ/scripts/run_scheduled_strategy_audits.sh"
)

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" \
  | grep -v 'proposal_monitor.py --pending' \
  | grep -v 'run_scheduled_strategy_audits.sh' > "$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  for ln in "${LINES[@]}"; do echo "$ln"; done
  echo "$END"
} | crontab -
rm -f "$TMP"

# Align enrichment throughput with crontab_backup.txt
TMP2=$(mktemp)
crontab -l 2>/dev/null \
  | sed 's|auto_enrichment_runner.py >>|auto_enrichment_runner.py --limit 40 >>|' \
  | sed 's|proposal_enrichment_loop.py --run --limit 5|proposal_enrichment_loop.py --run --limit 15|g' \
  > "$TMP2" || true
crontab "$TMP2"
rm -f "$TMP2"

echo "Installed strategy monitoring cron:"
crontab -l | grep -A8 "$MARKER"