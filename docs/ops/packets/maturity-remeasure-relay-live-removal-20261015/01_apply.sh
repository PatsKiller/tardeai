#!/usr/bin/env bash
# Config write (operator). Without APPLY=1: dry run only. With APPLY=1: backup copy, then atomic rewrite.
set -eu
P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
F="${LIVE_LANES_FILE:-$HOME/.config/tradeai/n8n-live-lanes.env}"
LANE=maturity-remeasure
if [ "${APPLY:-0}" != "1" ]; then
  python3 "$P/edit_live_lanes.py" --file "$F" --remove "$LANE"
  echo "(set APPLY=1 to write)"
  exit 0
fi
B="$F.pre-maturity-remeasure-removal-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$F" "$B"
echo "backup: $B ($(sha256sum "$B" | cut -c1-16))"
python3 "$P/edit_live_lanes.py" --file "$F" --remove "$LANE" --apply
echo "after: $(sha256sum "$F" | cut -c1-16)"
echo "Not in effect until both units restart: APPLY=1 bash $P/02_restart.sh"
