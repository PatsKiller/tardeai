#!/usr/bin/env bash
# consolidation-health-audit-c3-20261015 — FLIP (operator-run only, under a `cron` grant naming these lines).
#   bash install.sh                          # DRY RUN: builds the candidate from the LIVE table, prints the diff
#   CRON_GRANT_ID=<id> bash install.sh --apply
# One act: the four F36 weekday-morning lines are commented in place (`# RETIRED <date> c3-health-audit <step> ...`,
# never deleted) and ONE runner line (`run_health_audit_pipeline.sh --stage morning --apply`) is appended, so at no
# moment can both the old lines and the stage run the same check. Backup first; read back; restore on mismatch.
# CRONTAB_CMD may name a fake crontab for rehearsal (it must accept `-l` and `-`).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRONTAB_CMD="${CRONTAB_CMD:-crontab}"
APPLY=0
for a in "$@"; do case "$a" in --apply) APPLY=1 ;; *) echo "unknown argument: $a"; exit 2 ;; esac; done
W="${WORK_DIR:-$HOME/.local/state/tradeai/c3-health-audit/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$W"
"$CRONTAB_CMD" -l > "$W/crontab.live"
python3 "$HERE/flip_packet.py" build --crontab "$W/crontab.live" --date "$(date +%F)" --out "$W"
sed -n '3,$p' "$W/crontab.diff" | grep '^[-+]' | cut -c1-180 || true
if [ "$APPLY" != 1 ]; then echo "DRY RUN: nothing written (work dir $W)"; exit 0; fi
[ -n "${CRON_GRANT_ID:-}" ] || { echo "REFUSED: --apply needs CRON_GRANT_ID"; exit 2; }
bk="${BACKUP_DIR:-$HOME/.local/state/tradeai/backups}/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-c3-health-audit-${CRON_GRANT_ID:0:16}.txt"
mkdir -p "$(dirname "$bk")"; cp "$W/crontab.live" "$bk"
"$CRONTAB_CMD" -l | cmp -s - "$W/crontab.live" || { echo "REFUSED: crontab changed while building; re-run"; exit 2; }
"$CRONTAB_CMD" - < "$W/crontab.candidate.txt"
"$CRONTAB_CMD" -l > "$W/crontab.after"
cmp -s "$W/crontab.after" "$W/crontab.candidate.txt" || { echo "FAILED: read-back differs; restoring $bk"; "$CRONTAB_CMD" - < "$bk"; exit 1; }
python3 "$HERE/flip_packet.py" verify --crontab "$W/crontab.after"
echo "INSTALLED: backup $bk; work dir $W"
