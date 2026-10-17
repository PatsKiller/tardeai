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
#     (no owner row, or the slot's effect already happened) exits 75, as `flock -n` does, and runs nothing.
#   * 2026-10-16: whatever cron_claim says, owner n8n exits 0 (event skipped_effect) and runs nothing.
#   * 2026-10-16 (architect review, fail CLOSED for handed-over lanes): ownership comes from BOTH the ledger
#     (read-only) and the durable handover manifest (scripts/lib/effect_claim.py "durable handover manifest";
#     written only by `effect_claim.py set-owner`, read-only here). A process that was HANDED OVER to n8n (ledger
#     owner n8n, or manifest owner n8n/none) whose ownership cannot be established (ledger unreachable, manifest
#     unreadable, or the two stores DISAGREE) runs NOTHING: exit 75, event skipped_ownership_unknown, and one
#     EffectOwnershipIncident@v1 row in <state>/data/runtime/effect_ownership_incidents.jsonl, which
#     scripts/incident_notifier.py (host cron, independent of the ledger and n8n) pages as a P1. The two stores are
#     never reconciled here (AGENTS.md §0 rule 5): both values are in the event detail and the incident row.
#   * 2026-10-16 (second architect review, of 26fd0518, finding 2): with the ledger unreachable the manifest is the
#     ONLY admission evidence, so a manifest that is missing or does not list the process FAILS CLOSED (P1) for any
#     process whose key is ARMED (n8n_claim true - the default - or cron_claim true). Only a never-armed process
#     keeps the fail-OPEN (event run_unclaimed_ledger_unreachable / run_unclaimed_cron_claim_false), and a missing
#     manifest file still raises a P1. The decision, the claim and the child's start happen under the handover-
#     manifest lock (`effect_claim.py run --ownership-gate`), the fence `set-owner` and the controller also take.
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
SPEC="$("$PY3" "$EFFECT_PY" lane-spec --lane "$LANE" --config "$CONFIG" --with-n8n-claim)"
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
IFS=$'\t' read -r PROCESS VERSION CRON_CLAIM N8N_CLAIM <<<"$SPEC"
set +e
# Armed = the key arms claims on either side (cron_claim true, or n8n_claim true/unknown). An armed process never
# fails open (architect review of 26fd0518, finding 2).
ARMED=0
if [ "$CRON_CLAIM" = "1" ] || [ "${N8N_CLAIM:-1}" != "0" ]; then
  ARMED=1
fi

# 2026-10-16 (cron effect-claim wrap, docs/ops/packets/cron-effect-claim-wrap-20261016/; architect review): the
# owner decides, from the ledger AND the handover manifest. Since the second architect review (finding 2) the
# decision, the effect claim and the child's START all happen inside ONE `effect_claim.py run --ownership-gate`
# call that holds the handover-manifest lock (the same lock `set-owner` and the nightly controller take), so no
# ownership switch can land between "cron may run" and "the cron copy started":
#   run                     -> the command runs (claimed when cron_claim is true, unclaimed otherwise);
#   skip_owner_n8n          -> exit 0, event skipped_effect, nothing runs, no claim row;
#   skip_ownership_unknown  -> exit 75, event skipped_ownership_unknown, nothing runs, P1 incident row
#                              (now also: ledger unreachable AND the manifest missing / not listing an ARMED process);
#   no decision at all (interpreter/import failure, lock timeout) -> nothing ran; fail closed if a handover manifest
#                              exists or the process is armed, else fail open.
STATE_ROOT_DIR="${TRADEAI_STATE_ROOT:-$HOME/trade-ai-releases/persistent-state}"
INCIDENT_LOG="${EFFECT_OWNERSHIP_INCIDENT_LOG:-$STATE_ROOT_DIR/data/runtime/effect_ownership_incidents.jsonl}"
if [ -n "${TRADEAI_N8N_HANDOVER_MANIFEST:-}" ]; then
  MANIFEST="$TRADEAI_N8N_HANDOVER_MANIFEST"
elif [ -n "${TRADEAI_N8N_COORDINATION_LEDGER:-}" ]; then
  MANIFEST="$(dirname "$TRADEAI_N8N_COORDINATION_LEDGER")/n8n_handover_manifest.json"
else
  MANIFEST="$STATE_ROOT_DIR/data/governance/n8n_handover_manifest.json"
fi

raise_p1() {
  # reason (sanitised to a safe charset, so the JSON line needs no quoting). Written by bash so that a broken
  # interpreter still pages.
  local why ts
  why="$(printf '%s' "$1" | tr -c 'A-Za-z0-9_:=,./-' '_' | cut -c1-200)"
  ts="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
  mkdir -p "$(dirname "$INCIDENT_LOG")" 2>/dev/null || true
  printf '{"ts":"%s","schema":"EffectOwnershipIncident@v1","severity":"P1","lane":"%s","process":"%s","slot":"%s","reason":"%s"}\n' \
    "$ts" "$LANE" "${PROCESS:-unknown}" "$SLOT" "$why" >> "$INCIDENT_LOG" 2>/dev/null \
    || echo "effect_claim_cron: P1 incident row could not be written to $INCIDENT_LOG" >&2
}

skip_unknown() {
  log_event skipped_ownership_unknown 75 "process=$PROCESS $1"
  raise_p1 "$1"
  echo "effect_claim_cron: ownership of $PROCESS cannot be established ($1); fail closed, nothing run (P1 raised)" >&2
  exit 75
}

run_unclaimed_fail_open() {
  # Only for a process that is NOT armed and has NO handover manifest: the pre-effect-key behaviour.
  log_event run_unclaimed_ledger_unreachable 0 "process=$PROCESS ($1; fail open: never armed, no manifest)"
  echo "effect_claim_cron: ownership helper produced no decision ($1); running $PROCESS unclaimed (fail open)" >&2
  "${CMD[@]}"
  rc=$?
  log_event completed_unclaimed "$rc" "process=$PROCESS"
  exit "$rc"
}

CMD=("$@")
DECISION="$(mktemp "${TMPDIR:-/tmp}/effect_claim_decision.XXXXXX" 2>/dev/null)"
if [ -z "$DECISION" ]; then
  if [ -e "$MANIFEST" ] || [ "$ARMED" = 1 ]; then
    skip_unknown "decision_tmpfile_failed armed=$ARMED"
  fi
  run_unclaimed_fail_open "mktemp failed"
fi
: > "$DECISION"
GATE_ARGS=(--ownership-gate --manifest "$MANIFEST" --effect-config "$CONFIG")
if [ "$CRON_CLAIM" != "1" ]; then
  GATE_ARGS+=(--no-claim)
fi
"$PY3" "$EFFECT_PY" run "${GATE_ARGS[@]}" --process "$PROCESS" --slot "$SLOT" --input-version "$VERSION" \
  --scheduler cron --decision-out "$DECISION" -- "${CMD[@]}"
rc=$?
DECIDED="$(cat "$DECISION" 2>/dev/null)"
rm -f "$DECISION"
if [ -z "$DECIDED" ]; then
  # No decision was written: the command did NOT run (interpreter/import failure, handover lock timeout).
  if [ -e "$MANIFEST" ] || [ "$ARMED" = 1 ]; then
    skip_unknown "ownership_helper_failed:rc=$rc armed=$ARMED manifest_present=$([ -e "$MANIFEST" ] && echo 1 || echo 0)"
  fi
  run_unclaimed_fail_open "rc=$rc"
fi
PARSED="$(printf '%s' "$DECIDED" | "$PY3" -c 'import json,sys
d=json.load(sys.stdin); o=d.get("ownership") or {}; c=d.get("claim") or {}
print("\t".join(str(x) for x in (o.get("decision") or "", o.get("ledger_owner") or "", o.get("manifest_owner") or "",
      1 if o.get("p1") else 0, (o.get("reason") or "-").replace("\t", " "),
      "ok" if c.get("ok") else ("%s %s" % (c.get("reason") or "", c.get("owner") or "")).strip() or "none")))' 2>/dev/null)"
IFS=$'\t' read -r DECISION_KIND LEDGER_OWNER MANIFEST_OWNER OWN_P1 OWN_REASON CLAIM_REASON <<<"$PARSED"
OWN_DETAIL="ledger=$LEDGER_OWNER manifest=$MANIFEST_OWNER reason=$OWN_REASON"
case "$DECISION_KIND" in
  skip_ownership_unknown) skip_unknown "$OWN_DETAIL" ;;
  skip_owner_n8n)
    CC_TXT=false
    if [ "$CRON_CLAIM" = "1" ]; then CC_TXT=true; fi
    log_event skipped_effect 0 "process=$PROCESS owner=n8n cron_claim=$CC_TXT $OWN_DETAIL"
    echo "effect_claim_cron: $PROCESS is owned by n8n; cron copy skipped (nothing run)" >&2
    exit 0 ;;
  run) ;;
  *)
    # The decision file exists but cannot be read back: the child MAY have run; never re-run it.
    log_event refused_claim "$rc" "process=$PROCESS decision unparsed (rc=$rc)"
    raise_p1 "decision_unparsed:rc=$rc"
    exit "$rc" ;;
esac
if [ "$OWN_P1" = "1" ]; then
  raise_p1 "$OWN_REASON"            # e.g. the handover manifest is missing (a never-armed process still ran)
fi

if [ "$CRON_CLAIM" != "1" ]; then
  OWNER="$LEDGER_OWNER"
  if [ "$OWNER" = "unreachable" ]; then
    OWNER="ledger_unreachable"
  fi
  log_event run_unclaimed_cron_claim_false 0 "process=$PROCESS owner=${OWNER:-none} $OWN_DETAIL"
  log_event completed_unclaimed "$rc" "process=$PROCESS"
  exit "$rc"
fi
case "$CLAIM_REASON" in
  ok) log_event completed_claimed "$rc" "process=$PROCESS" ;;
  "effect_fenced_owner n8n")
    log_event skipped_effect 0 "process=$PROCESS owner=n8n cron_claim=true"
    echo "effect_claim_cron: $PROCESS is owned by n8n; cron copy skipped (nothing run)" >&2
    exit 0 ;;
  *) log_event refused_claim 75 "process=$PROCESS reason=${CLAIM_REASON:-unparsed} (claim JSON on stderr)" ;;
esac
exit "$rc"
