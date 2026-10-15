#!/usr/bin/env bash
# lane-retire-wave1-20261015 — ROLLBACK (operator-run only, cron grant). Default DRY RUN; --apply writes.
#   bash rollback.sh [--tier-b]
#   CRON_GRANT_ID=<id> bash rollback.sh [--tier-b] --apply
# Uncomments exactly the lines tagged `# RETIRED <date> retire-ld-w1 <reason> ` whose original text is in the packet's
# TSV(s). Refuses if the tagged count is not the packet's count or if an uncommented copy is already live (double
# schedule). Works on the live table: lines changed since install by anything else are kept as they are.
# CRONTAB_CMD may name a fake crontab for rehearsal.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRONTAB_CMD="${CRONTAB_CMD:-crontab}"
APPLY=0; TIERB=()
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --tier-b) TIERB=(--tier-b) ;;
    *) echo "unknown argument: $a"; exit 2 ;;
  esac
done
W="${WORK_DIR:-$HOME/.local/state/tradeai/lane-retire-wave1/rollback-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$W"
"$CRONTAB_CMD" -l > "$W/crontab.live"
python3 "$HERE/retire_packet.py" rollback --crontab "$W/crontab.live" "${TIERB[@]}" --out "$W/crontab.restored"
diff -u "$W/crontab.live" "$W/crontab.restored" | sed -n '3,$p' | grep '^[-+]' | cut -c1-180 || true
if [ "$APPLY" != 1 ]; then echo "DRY RUN: nothing written (work dir $W)"; exit 0; fi
[ -n "${CRON_GRANT_ID:-}" ] || { echo "REFUSED: --apply needs CRON_GRANT_ID"; exit 2; }
bk="${BACKUP_DIR:-$HOME/.local/state/tradeai/backups}/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-retire-ld-w1-rollback.txt"
mkdir -p "$(dirname "$bk")"; cp "$W/crontab.live" "$bk"
"$CRONTAB_CMD" -l | cmp -s - "$W/crontab.live" || { echo "REFUSED: crontab changed while building; re-run"; exit 2; }
"$CRONTAB_CMD" - < "$W/crontab.restored"
"$CRONTAB_CMD" -l | cmp -s - "$W/crontab.restored" || { echo "FAILED: read-back differs; restoring $bk"; "$CRONTAB_CMD" - < "$bk"; exit 1; }
"$CRONTAB_CMD" -l > "$W/crontab.after"
python3 "$HERE/retire_packet.py" verify --crontab "$W/crontab.after" "${TIERB[@]}" --expect-live
echo "ROLLED BACK: backup $bk"
