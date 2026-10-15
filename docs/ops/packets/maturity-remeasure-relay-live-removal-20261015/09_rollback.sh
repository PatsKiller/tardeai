#!/usr/bin/env bash
# Rollback (operator): restore the newest pre-removal backup, restart both units. Nothing is deleted.
set -eu
P="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
F="${LIVE_LANES_FILE:-$HOME/.config/tradeai/n8n-live-lanes.env}"
B="$(ls -1 "$F".pre-maturity-remeasure-removal-* 2>/dev/null | sort | tail -1 || true)"
[ -n "$B" ] || { echo "no backup found next to $F"; exit 1; }
echo "restore from: $B"
if [ "${APPLY:-0}" != "1" ]; then echo "(set APPLY=1 to restore)"; exit 0; fi
cp -p "$F" "$F.pre-rollback-$(date -u +%Y%m%dT%H%M%SZ)"
cp -p "$B" "$F"
APPLY=1 bash "$P/02_restart.sh"
if grep -qw maturity-remeasure "$F"; then echo "ROLLBACK OK: maturity-remeasure back on the list"; else echo "ROLLBACK CHECK FAILED"; exit 1; fi
