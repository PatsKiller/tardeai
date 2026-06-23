#!/usr/bin/env bash
# Install intraday Finviz portfolio repricer (every 15 min, market hours ET).
# Safe to re-run — skips if marker already present.
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
MARKER="# BEGIN finviz-intraday-repricer"
LINE='*/15 9-16 * * 1-5 cd '"$PROJ"' && bash '"$PROJ"'/scripts/safe_flock.sh /tmp/portfolio_repricer.lock '"$PROJ"'/.venv/bin/python scripts/portfolio_repricer.py >> '"$PROJ"'/logs/portfolio_repricer_intraday.log 2>&1'
PREMARKET='5 9 * * 1-5 cd '"$PROJ"' && bash '"$PROJ"'/scripts/safe_flock.sh /tmp/portfolio_repricer.lock '"$PROJ"'/.venv/bin/python scripts/portfolio_repricer.py >> '"$PROJ"'/logs/portfolio_repricer_intraday.log 2>&1'

TMP=$(mktemp)
crontab -l 2>/dev/null | grep -v "$MARKER" | grep -v "END finviz-intraday-repricer" | grep -v "portfolio_repricer_intraday.log" > "$TMP" || true
{
  cat "$TMP"
  echo "$MARKER"
  echo "$LINE"
  echo "$PREMARKET"
  echo "# END finviz-intraday-repricer"
} | crontab -
rm -f "$TMP"
echo "Installed Finviz intraday repricer:"
echo "  - every 15 min 9:00-16:59 ET Mon-Fri"
echo "  - pre-open kick 9:05 ET Mon-Fri"
crontab -l | grep -A3 "$MARKER"