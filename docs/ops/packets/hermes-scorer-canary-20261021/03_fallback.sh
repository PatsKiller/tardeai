#!/usr/bin/env bash
# hermes-scorer fallback (cron grant): put cron L451 back. Uncomments ONLY the line tagged
# `# RETIRED <date> n8n-cutover hermes-watchlist-scorer ` (written by 02_retire_cron_line.sh) by stripping that tag;
# every other line is byte-identical. Never a wholesale crontab restore.
#   bash 03_fallback.sh            dry run (default): shows the line before/after
#   bash 03_fallback.sh --apply    backup, write, read back
# The n8n side needs no change to fall back: with both firing, the shared flock /tmp/hermes_scorer.lock keeps one run
# per slot. To stop n8n firing it too, remove the lane from the live list (README rollback R2).
set -euo pipefail
LANE=hermes-watchlist-scorer
CRONTAB_BIN=${CRONTAB_BIN:-crontab}
BACKUP_DIR=${BACKUP_DIR:-$HOME/.local/state/tradeai/backups}
APPLY=0
case "${1:-}" in --apply) APPLY=1 ;; "") ;; *) echo "usage: $0 [--apply]"; exit 2 ;; esac
fail(){ echo "REFUSED: $*"; exit 1; }

CUR=$("$CRONTAB_BIN" -l)
NEW=$(LANE="$LANE" python3 -c '
import os, re, sys
lane = os.environ["LANE"]
tag = re.compile(r"^#\s*RETIRED\s+\d{4}-\d{2}-\d{2}\s+n8n-cutover\s+" + re.escape(lane) + r"\s(.*)$")
lines = sys.stdin.read().split("\n")
hits = [i for i, ln in enumerate(lines) if tag.match(ln)]
if len(hits) != 1:
    sys.stderr.write(f"expected exactly 1 tagged line for {lane}, found {len(hits)}\n"); sys.exit(1)
i = hits[0]
orig = tag.match(lines[i]).group(1)
if "scripts/hermes_watchlist_scorer.py" not in orig or orig.lstrip().startswith("#"):
    sys.stderr.write("tagged line does not hold the scorer cron line\n"); sys.exit(1)
sys.stderr.write(f"  L{i + 1} before: {lines[i][:160]}\n  L{i + 1} after : {orig[:160]}\n")
lines[i] = orig
sys.stdout.write("\n".join(lines))
' <<<"$CUR") || fail "no single retired scorer line to restore"
[[ $APPLY == 1 ]] || { echo "DRY RUN - crontab unchanged"; exit 0; }

mkdir -p "$BACKUP_DIR"
BK="$BACKUP_DIR/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-fallback-$LANE.txt"
printf '%s\n' "$CUR" > "$BK"
printf '%s\n' "$NEW" | "$CRONTAB_BIN" -
"$CRONTAB_BIN" -l | grep -v '^[[:space:]]*#' | grep -c 'scripts/hermes_watchlist_scorer.py' | grep -qx 1 \
  || fail "READ-BACK FAILED: expected exactly 1 live scorer line (backup $BK)"
echo "APPLIED: cron L451 restored (backup $BK)"
