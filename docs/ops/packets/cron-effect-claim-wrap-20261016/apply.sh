#!/usr/bin/env bash
# Wrap every cutover-candidate cron line in scripts/effect_claim_cron.sh (packet cron-effect-claim-wrap-20261016).
# DRY RUN BY DEFAULT: builds the candidate from the LIVE crontab, backs it up, checks it and prints the diff.
#   bash apply.sh            dry run (writes only the work dir under ~/.local/state/tradeai/backups/)
#   bash apply.sh --apply    OPERATOR ONLY: needs an active `cron` grant whose reason names this packet
# n8n cutover standard (memory 2026-10-14): fix + dry run + regression + one live n8n run; no soak.
set -euo pipefail
set -f

MODE="${1:-dry-run}"
case "$MODE" in dry-run|--dry-run) MODE=dry-run ;; --apply) MODE=apply ;; *) echo "usage: apply.sh [--apply]" >&2; exit 2 ;; esac

PK="$(cd "$(dirname "$0")" && pwd)"
PY3="${PY3:-python3}"
SERVED="${SERVED:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
W="${BACKUP_ROOT:-$HOME/.local/state/tradeai/backups}/cron-effect-claim-wrap-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$W"

# 1. Candidate from the LIVE crontab (never a candidate generated earlier); the backup is taken first.
crontab -l > "$W/crontab.live"
cp -p "$W/crontab.live" "$W/crontab.backup"
"$PY3" "$PK/plan.py" --crontab "$W/crontab.live" --emit-candidate "$W/crontab.candidate" --json > "$W/plan.json"
"$PY3" "$PK/plan.py" --crontab "$W/crontab.live" > "$W/plan.txt"
PLANNED="$("$PY3" -c 'import json,sys; print(json.load(open(sys.argv[1]))["wrapped_count"])' "$W/plan.json")"
SKIPPED="$("$PY3" -c 'import json,sys; print(json.load(open(sys.argv[1]))["skipped_count"])' "$W/plan.json")"
echo "planned wraps: $PLANNED   reported skips: $SKIPPED   work dir: $W"

# 2. Checks: the diff count equals the planned count, the line count is unchanged, and removing the wrapper prefixes
#    from the candidate gives the same bytes as removing them from the live crontab (nothing else moved; lines wrapped
#    by an earlier apply are allowed and counted).
ADDED="$(diff "$W/crontab.live" "$W/crontab.candidate" | grep -c '^>' || true)"
REMOVED="$(diff "$W/crontab.live" "$W/crontab.candidate" | grep -c '^<' || true)"
test "$ADDED" = "$PLANNED" && test "$REMOVED" = "$PLANNED" \
  || { echo "CHECK FAIL: diff +$ADDED/-$REMOVED != planned $PLANNED"; exit 4; }
test "$(wc -l < "$W/crontab.live")" = "$(wc -l < "$W/crontab.candidate")" || { echo "CHECK FAIL: line count moved"; exit 4; }
"$PY3" "$PK/plan.py" --unwrap --crontab "$W/crontab.candidate" --emit-candidate "$W/candidate.unwrapped" > "$W/unwrap.cand"
"$PY3" "$PK/plan.py" --unwrap --crontab "$W/crontab.live" --emit-candidate "$W/live.unwrapped" > "$W/unwrap.live"
U_CAND="$(sed -n 's/^UNWRAP_COUNT=//p' "$W/unwrap.cand")"
U_LIVE="$(sed -n 's/^UNWRAP_COUNT=//p' "$W/unwrap.live")"
test "$((U_CAND - U_LIVE))" = "$PLANNED" || { echo "CHECK FAIL: unwrap delta $U_CAND-$U_LIVE != $PLANNED"; exit 4; }
cmp "$W/live.unwrapped" "$W/candidate.unwrapped" || { echo "CHECK FAIL: candidate differs beyond the wrapper prefixes"; exit 4; }
echo "checks OK: diff count = planned = $PLANNED; candidate == live apart from the wrapper prefixes (byte-exact)"
diff "$W/crontab.live" "$W/crontab.candidate" > "$W/crontab.diff" || true

if [ "$PLANNED" = 0 ]; then
  echo "nothing to wrap"; exit 0
fi

if [ "$MODE" = dry-run ]; then
  sed -n '1,3p' "$W/plan.txt"
  cat "$W/crontab.diff"
  echo "DRY RUN: nothing installed. Re-run with --apply (operator, cron grant)."
  exit 0
fi

# 3. Preconditions for --apply (each prints OK or stops)
grep -q 'skipped_effect' "$SERVED/scripts/effect_claim_cron.sh" \
  && grep -q 'run_unclaimed_ledger_unreachable' "$SERVED/scripts/effect_claim_cron.sh" \
  && grep -q 'decision-out' "$SERVED/scripts/lib/effect_claim.py" && echo "P1 OK served wrapper has the 10-16 semantics" \
  || { echo "P1 FAIL: $SERVED does not serve the 10-16 wrapper (promote the PR first)"; exit 3; }
guard show | sed 's/\x1b\[[0-9;]*m//g' | grep -i cron || { echo "P2 FAIL: no active cron grant"; exit 3; }
crontab -l | cmp - "$W/crontab.live" && echo "P3 OK crontab unchanged since the plan" \
  || { echo "P3 FAIL: the crontab changed while planning; re-run"; exit 3; }

# 4. Install with `crontab -` and read it back byte-exact
crontab - < "$W/crontab.candidate"
crontab -l | cmp - "$W/crontab.candidate" && echo "installed exactly ($PLANNED lines wrapped)"
echo "verify: tail -f $SERVED/logs/effect_claim_events.jsonl   (skipped_effect = n8n owns the lane)"
echo "rollback: bash $PK/rollback.sh --apply   (or: crontab - < $W/crontab.backup if nothing else changed)"
