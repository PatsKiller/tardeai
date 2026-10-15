#!/usr/bin/env bash
# lane-retire-wave1-20261015 — INSTALL (operator-run only, under a `cron` grant naming these lines).
#   bash install.sh [--tier-b]                       # DRY RUN: builds the candidate from the LIVE table, prints the diff
#   CRON_GRANT_ID=<id> bash install.sh [--tier-b] --apply
# The candidate is always rebuilt from `crontab -l` at run time (never a candidate generated earlier). Each retired
# line is commented in place `# RETIRED <date> retire-ld-w1 <reason> <original>`; nothing is deleted. --apply backs the
# table up first, writes with `crontab -`, re-reads it and restores the backup if the read-back differs.
# --tier-b adds lines_to_retire_tier_b.tsv: pass it only for the rows you answered YES in README.md.
# CRONTAB_CMD may name a fake crontab for rehearsal (it must accept `-l` and `-`).
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
W="${WORK_DIR:-$HOME/.local/state/tradeai/lane-retire-wave1/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$W"
"$CRONTAB_CMD" -l > "$W/crontab.live"
python3 "$HERE/retire_packet.py" build --crontab "$W/crontab.live" --date "$(date +%F)" "${TIERB[@]}" --out "$W"
sed -n '3,$p' "$W/crontab.diff" | grep '^[-+]' | cut -c1-180 || true
if [ "$APPLY" != 1 ]; then echo "DRY RUN: nothing written (work dir $W). Re-run with CRON_GRANT_ID=<id> ... --apply"; exit 0; fi
[ -n "${CRON_GRANT_ID:-}" ] || { echo "REFUSED: --apply needs CRON_GRANT_ID (the operator's cron grant id)"; exit 2; }
bk="${BACKUP_DIR:-$HOME/.local/state/tradeai/backups}/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-retire-ld-w1-${CRON_GRANT_ID:0:16}.txt"
mkdir -p "$(dirname "$bk")"; cp "$W/crontab.live" "$bk"
# The table must not have changed between the read and the write.
"$CRONTAB_CMD" -l | cmp -s - "$W/crontab.live" || { echo "REFUSED: crontab changed while building; re-run"; exit 2; }
"$CRONTAB_CMD" - < "$W/crontab.candidate.txt"
"$CRONTAB_CMD" -l > "$W/crontab.after"
if ! cmp -s "$W/crontab.after" "$W/crontab.candidate.txt"; then
  echo "FAILED: read-back differs from the candidate; restoring $bk"; "$CRONTAB_CMD" - < "$bk"; exit 1
fi
python3 "$HERE/retire_packet.py" verify --crontab "$W/crontab.after" "${TIERB[@]}"
echo "INSTALLED: crontab sha $(sha256sum < "$W/crontab.after" | cut -d' ' -f1); backup $bk; work dir $W"
