#!/usr/bin/env bash
# ROLLBACK packet cron-effect-claim-wrap-20261016. Removes exactly the wrapper prefix this packet inserted
# (`env TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane> `) from the LIVE crontab, so any other
# edit made since the apply is kept. Nothing else needs undoing: the wrapper writes only its own event log and, for an
# armed lane, effect_claims rows that the n8n side reads the same way.
#   bash rollback.sh            dry run (prints the diff)
#   bash rollback.sh --apply    OPERATOR ONLY (cron grant)
set -euo pipefail
set -f

MODE="${1:-dry-run}"
case "$MODE" in dry-run|--dry-run) MODE=dry-run ;; --apply) MODE=apply ;; *) echo "usage: rollback.sh [--apply]" >&2; exit 2 ;; esac

PK="$(cd "$(dirname "$0")" && pwd)"

# Grant check (fixed 2026-10-16: the operator's --apply failed twice). `guard` is not on PATH, so use the repo's
# bin/guard; and `guard show` exits 1 even when it prints the active grants, so under pipefail the old
# `guard show | sed | grep` false-failed. Capture the output first, then grep the stripped text.
REPO_ROOT="${REPO_ROOT:-$(git -C "$PK" rev-parse --show-toplevel 2>/dev/null || (cd "$PK/../../../.." && pwd))}"
GUARD_BIN="${GUARD_BIN:-$REPO_ROOT/bin/guard}"
cron_grant_active() {
  local out
  [ -x "$GUARD_BIN" ] || { echo "guard not found at $GUARD_BIN (set GUARD_BIN)" >&2; return 1; }
  out="$("$GUARD_BIN" show 2>&1)" || true
  printf '%s\n' "$out" | sed 's/\x1b\[[0-9;]*m//g' | grep -iE '^[[:space:]]*cron[[:space:]]'
}
PY3="${PY3:-python3}"
W="${BACKUP_ROOT:-$HOME/.local/state/tradeai/backups}/cron-effect-claim-wrap-rollback-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$W"
crontab -l > "$W/crontab.live"
cp -p "$W/crontab.live" "$W/crontab.backup"
"$PY3" "$PK/plan.py" --unwrap --crontab "$W/crontab.live" --emit-candidate "$W/crontab.candidate" > "$W/unwrap.txt"
N="$(sed -n 's/^UNWRAP_COUNT=//p' "$W/unwrap.txt")"
CHANGED="$(diff "$W/crontab.live" "$W/crontab.candidate" | grep -c '^>' || true)"
test "$CHANGED" = "$N" || { echo "CHECK FAIL: diff $CHANGED != unwrap $N"; exit 4; }
echo "lines to unwrap: $N   work dir: $W"
if [ "$N" = 0 ]; then echo "nothing to roll back"; exit 0; fi
if [ "$MODE" = dry-run ]; then
  diff "$W/crontab.live" "$W/crontab.candidate" || true
  echo "DRY RUN: nothing installed. Re-run with --apply (operator, cron grant)."
  exit 0
fi
cron_grant_active || { echo "FAIL: no active cron grant"; exit 3; }
crontab -l | cmp - "$W/crontab.live" || { echo "FAIL: the crontab changed while planning; re-run"; exit 3; }
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "rolled back exactly ($N lines)"
