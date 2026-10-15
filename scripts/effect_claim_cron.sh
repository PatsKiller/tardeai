#!/usr/bin/env bash
# effect_claim_cron.sh: cron-side semantic effect-key claim for a lane that has no manifest runner.
#
# Usage (inside the existing lock, so the flock still refuses an overlap):
#   flock -n /tmp/x.lock bash scripts/effect_claim_cron.sh LANE_ID COMMAND [ARGS...]
#
# 2026-10-15 (canary double-effect audit, CANARY_DOUBLE_EFFECT_AUDIT.md section 4; AGENTS.md §23.23 rule (4)).
# A shared `flock -n` stops a cron run and an n8n run from OVERLAPPING, not from running one after the other in the
# same slot. This wrapper makes the cron line claim the same key the n8n executor claims,
# fx:<process>:<slot>:<input_version> (scripts/lib/effect_claim.py), so the second scheduler to reach a slot runs
# nothing.
#
# OFF BY DEFAULT, ON PER LINE. Unless the line sets TRADEAI_EFFECT_CLAIM to exactly this LANE_ID, the wrapper
# `exec`s the command unchanged: no python, no ledger, no event, same exit code. Matching the lane id (not "1")
# means a crontab-wide export cannot switch on every wrapped line at once. A cron line switches on like this:
#   ... flock -n /tmp/x.lock env TRADEAI_EFFECT_CLAIM=x-lane bash scripts/effect_claim_cron.sh x-lane $PY scripts/x.py
#
# When switched on:
#   * the lane must be keyed in config/n8n_effect_keys.json, and the config must be readable; otherwise exit 65
#     and run nothing (fail closed: either scheduler might own the effect);
#   * a keyed lane with cron_claim false runs unchanged (the config has not armed its cron side yet; the cutover
#     packet flips cron_claim after `effect_claim.py set-owner --owner cron` has created the owner row);
#   * a lane with cron_claim true runs through `effect_claim.py run --scheduler cron --slot now`: a refused claim
#     (no owner row, n8n owns it, or the slot's effect already happened) exits 75, as `flock -n` does, and runs
#     nothing. An unreadable ledger exits 2 and runs nothing.
# --slot now is the America/New_York minute, the slot of the dispatcher's d: key for the same scheduled minute.
# TRADEAI_EFFECT_SLOT overrides it (a manual re-fire of a named slot, and tests).
#
# safe_flock-style: never a silent skip. Every switched-on decision is one JSON line in
# logs/effect_claim_events.jsonl, and the child's exit code is preserved. A child that itself exits 75 reads as a
# refusal in the event log; the claim JSON on stderr (in the cron log) says which.
#
# AUTHORITY: READ_ONLY_ADVISORY. Writes only the effect_claims/effect_owners tables (via effect_claim.py) and its
# own event log. No send, no broker.

set -u

LANE="${1:-}"
if [ -n "$LANE" ]; then
  shift || true
fi
if [ -z "$LANE" ] || [ "$#" -lt 1 ]; then
  echo "Usage: effect_claim_cron.sh LANE_ID COMMAND [ARGS...]" >&2
  exit 2
fi

# OFF: byte-for-byte the command the cron line ran before.
if [ "${TRADEAI_EFFECT_CLAIM:-}" != "$LANE" ]; then
  exec "$@"
fi

PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY3="${EFFECT_CLAIM_PY:-python3}"
EFFECT_PY="$PROJECT_ROOT/scripts/lib/effect_claim.py"
CONFIG="${TRADEAI_EFFECT_CLAIM_CONFIG:-$PROJECT_ROOT/config/n8n_effect_keys.json}"
SLOT="${TRADEAI_EFFECT_SLOT:-now}"
LOG_DIR="${EFFECT_CLAIM_LOG_DIR:-$PROJECT_ROOT/logs}"
mkdir -p "$LOG_DIR" 2>/dev/null || true
EVENT_LOG="$LOG_DIR/effect_claim_events.jsonl"

log_event() {
  # event, exit_code, detail
  "$PY3" -c 'import json,sys,datetime
lane, ev, rc, detail, slot = sys.argv[1:6]
print(json.dumps({"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(), "schema": "EffectClaimCronEvent@v1",
                  "lane": lane, "event": ev, "exit_code": int(rc), "slot": slot, "detail": detail}))' \
    "$LANE" "$1" "$2" "$3" "$SLOT" >> "$EVENT_LOG" 2>/dev/null || true
}

set +e
SPEC="$("$PY3" "$EFFECT_PY" lane-spec --lane "$LANE" --config "$CONFIG")"
spec_rc=$?
if [ "$spec_rc" = 3 ]; then
  log_event refused_not_keyed 65 "lane not in $CONFIG"
  echo "effect_claim_cron: $LANE is not keyed in $CONFIG; refusing (nothing run)" >&2
  exit 65
fi
if [ "$spec_rc" != 0 ]; then
  log_event refused_config_unreadable 65 "lane-spec rc=$spec_rc"
  echo "effect_claim_cron: effect-key config unreadable (rc=$spec_rc); refusing (nothing run)" >&2
  exit 65
fi
IFS=$'\t' read -r PROCESS VERSION CRON_CLAIM <<<"$SPEC"
set +e

if [ "$CRON_CLAIM" != "1" ]; then
  log_event run_unclaimed_cron_claim_false 0 "process=$PROCESS"
  "$@"
  rc=$?
  log_event completed_unclaimed "$rc" "process=$PROCESS"
  exit "$rc"
fi

"$PY3" "$EFFECT_PY" run --process "$PROCESS" --slot "$SLOT" --input-version "$VERSION" --scheduler cron -- "$@"
rc=$?
case "$rc" in
  75) log_event refused_claim 75 "process=$PROCESS (effect_claim.py run refused; claim JSON on stderr)" ;;
  2) log_event exit_2_ledger_error_or_child 2 "process=$PROCESS (exit 2 = ledger/key error before the run, or the child's own exit 2; stderr says which)" ;;
  *) log_event completed_claimed "$rc" "process=$PROCESS" ;;
esac
exit "$rc"
