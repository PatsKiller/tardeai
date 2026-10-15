#!/usr/bin/env bash
# consolidation-health-audit-c3-20261015 — ROLLBACK (operator-run only, cron grant). Default DRY RUN; --apply writes.
#   bash rollback.sh
#   CRON_GRANT_ID=<id> bash rollback.sh --apply
# Removes the one runner line and uncomments exactly the four tagged step lines. Refuses on a count mismatch or a
# double schedule. Works on the live table; other edits since install are kept.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRONTAB_CMD="${CRONTAB_CMD:-crontab}"
APPLY=0
for a in "$@"; do case "$a" in --apply) APPLY=1 ;; *) echo "unknown argument: $a"; exit 2 ;; esac; done
W="${WORK_DIR:-$HOME/.local/state/tradeai/c3-health-audit/rollback-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$W"
"$CRONTAB_CMD" -l > "$W/crontab.live"
python3 "$HERE/flip_packet.py" rollback --crontab "$W/crontab.live" --out "$W/crontab.restored"
diff -u "$W/crontab.live" "$W/crontab.restored" | sed -n '3,$p' | grep '^[-+]' | cut -c1-180 || true
if [ "$APPLY" != 1 ]; then echo "DRY RUN: nothing written (work dir $W)"; exit 0; fi
[ -n "${CRON_GRANT_ID:-}" ] || { echo "REFUSED: --apply needs CRON_GRANT_ID"; exit 2; }
bk="${BACKUP_DIR:-$HOME/.local/state/tradeai/backups}/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-c3-health-audit-rollback.txt"
mkdir -p "$(dirname "$bk")"; cp "$W/crontab.live" "$bk"
"$CRONTAB_CMD" -l | cmp -s - "$W/crontab.live" || { echo "REFUSED: crontab changed while building; re-run"; exit 2; }
"$CRONTAB_CMD" - < "$W/crontab.restored"
"$CRONTAB_CMD" -l | cmp -s - "$W/crontab.restored" || { echo "FAILED: read-back differs; restoring $bk"; "$CRONTAB_CMD" - < "$bk"; exit 1; }
"$CRONTAB_CMD" -l > "$W/crontab.after"
python3 "$HERE/flip_packet.py" verify --crontab "$W/crontab.after" --expect-live
echo "ROLLED BACK: backup $bk"
