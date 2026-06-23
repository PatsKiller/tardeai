#!/usr/bin/env bash
# Install centralized health_agent.py cron (every 30 min, 7 days).
# Safe to re-run — replaces only the marked block.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
MARKER="# BEGIN health-agent-cron"
END="# END health-agent-cron"
LINE='*/30 * * * * cd '"$PROJ"' && '"$PROJ"'/.venv/bin/python scripts/health_agent.py >> '"$PROJ"'/logs/health_agent_cron.log 2>&1'

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "$END" | grep -v 'logs/health_agent_cron.log' > "$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  echo "$LINE"
  echo "$END"
} | crontab -
rm -f "$TMP"
echo "Installed Health Agent cron:"
echo "  - every 30 min, 7 days/week"
crontab -l | grep -A2 "$MARKER"