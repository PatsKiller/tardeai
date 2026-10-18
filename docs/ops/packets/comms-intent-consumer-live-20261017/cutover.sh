#!/usr/bin/env bash
# comms-intent consumer LIVE on the n8n fabric at */5. Operator decision D2 2026-10-17 "Queue reader first"
# (docs/ops/packets/hermes-learning-cutover-20261015/README.md). Cutover standard 2026-10-14: fix + dry run +
# regression + >=1 live n8n run, no soak. Dry by default; nothing here deletes anything.
#
# Lane n8n-comms-intent-consumer (scripts/n8n_comms_intent_consumer.py --apply) is n8n-native: no cron line or unit
# ever existed. tradeai-dispatcher (already active, shared by every dispatch-live lane) fires it every 5 min once the
# served registry row says stage canary / dispatch live AND the lane is in TRADEAI_N8N_RELAY_LIVE_LANES; until then the
# gateway demotes the fire to dry_run (relay_live_not_enabled), which is mode=ro and writes nothing.
#
#   bash cutover.sh pre                     read-only: served PR state, live list, units, dispatcher row, ledger
#                                           backlog, a served --dry-run of the consumer, notifier delivery window
#   bash cutover.sh relay    [--apply]      live list += the lane; backup + read-back; restart relay AND gateway
#                                           (config-write + service grant). Refused while the notifier cannot deliver
#                                           (quiet hours 22:00-06:59 ET or daily cap used) unless ACCEPT_DELIVERY_GAP=1
#   bash cutover.sh publish                 read-only: NO import is needed (no workflow changes); confirms the served
#                                           tradeai-dispatcher.json matches INDEX and the n8n row is active
#   bash cutover.sh proof [--since ISO]     read-only: live RUN_DONE runs with output verdict produced|empty_allowed,
#                                           intents QUEUED -> DONE, incidents, fan-in note, notifier delivery receipt
#   bash cutover.sh rollback [--apply]      live list -= the lane (backup + read-back); restart relay AND gateway.
#                                           NEVER deactivates tradeai-dispatcher (it fires every other live lane)
#
# Order: (merge + promote the PR so CURRENT serves it) -> pre -> relay --apply -> publish -> wait one */5 slot ->
# proof. TRADEAI_FABRIC_GRANT (the config-write grant id) is required for every --apply.
# This script never touches a broker, an order, a secret value, the crontab or an n8n workflow.
# Test hooks (hermetic tests only): SYSTEMCTL_BIN, DOCKER_BIN, NOW_HM (HHMM ET), NOTIFIER_RECEIPT, PROC_ROOT.
set -euo pipefail
set -f
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
GRANT_PY=${GRANT_PY:-$(cd "$(dirname "$0")/../../../.." && pwd)/scripts/lib/fabric_grant.py}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER=${LEDGER:-$STATE/data/governance/n8n_coordination_ledger.sqlite}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
NOTIFIER_RECEIPT=${NOTIFIER_RECEIPT:-$STATE/data/runtime/incident_notifier_last.json}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
DOCKER_BIN=${DOCKER_BIN:-docker}
PROC_ROOT=${PROC_ROOT:-/proc}
LANE=n8n-comms-intent-consumer
WID=tradeai-dispatcher
UNITS=(tradeai-n8n-run-relay tradeai-n8n-coordination-gateway)
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=${1:-}; shift || true
APPLY=0; SINCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --since) SINCE=${2:-}; shift 2 ;; *) fail "unknown arg $1" ;; esac
done
# The value must be the id of an ACTIVE config-write or cron guard grant (TRADEAI_FABRIC_GRANT=$(bin/guard id config-write));
# a free-text label is refused. Read-only check of the guard ledger; it consumes no use.
need_grant(){
  [[ $APPLY == 0 ]] && return 0
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
  local hit
  hit=$("$PY" "$GRANT_PY" verify "$TRADEAI_FABRIC_GRANT" config-write,cron) || fail "TRADEAI_FABRIC_GRANT is not an active config-write/cron grant id (bin/guard id config-write)"
  echo "  grant ok: $hit"
}
now_hm(){ echo "${NOW_HM:-$(TZ=America/New_York date +%H%M)}"; }
live_lanes(){ sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV"; }
in_live_list(){ [[ -f "$LIVE_LANES_ENV" ]] && live_lanes | tr ' ' '\n' | grep -qx -- "$LANE"; }

served_state(){ # the served comms-consumer-live facts; exit 1 unless the PR is served
  SERVED="$SERVED" "$PY" - "$LANE" <<'EOF'
import json, os, sys
root, lane = os.environ["SERVED"], sys.argv[1]
j = lambda rel: json.load(open(os.path.join(root, rel)))
reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}.get(lane) or {}
allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}.get(lane) or {}
hc = {c["id"]: c for c in j("config/n8n_health_contracts.json")["contracts"]}.get(lane) or {}
sched, disp = reg.get("scheduler") or {}, reg.get("dispatch") or {}
src = open(os.path.join(root, "scripts/n8n_comms_intent_consumer.py")).read()
checks = {
    "registry scheduler n8n/dispatcher stage canary": (sched.get("kind"), sched.get("expression"), sched.get("stage"))
    == ("n8n", "dispatcher", "canary"),
    "registry dispatch live */5": disp.get("mode") == "live" and disp.get("cron") == ["*/5 * * * *"],
    "allowlist live_arg --apply": allow.get("live_arg") == ["--apply"],
    "allowlist output_receipt v2": allow.get("output_receipt") == "v2",
    "health contract REVIEWED canary + expected_output": hc.get("status") == "REVIEWED"
    and hc.get("stage") == "canary" and (hc.get("expected_output") or {}).get("rule") == "empty_allowed",
    "consumer writes LaneRunReceipt@v2 output": "def lane_output" in src and "output=output" in src,
}
for name, good in checks.items():
    print(f"  {'ok ' if good else 'BAD'} {name}")
ok = all(checks.values())
print(f"  served {os.path.basename(root)}: " + ("COMMS CONSUMER LIVE PR SERVED" if ok else "PR NOT served (merge, then promote): stop here"))
sys.exit(0 if ok else 1)
EOF
}

delivery_window(){ # can the notifier deliver a P2 now? A comms incident stays OPEN 1 h (dedupe_window_s), and the
  # notifier only sends what is open at send time: inside quiet hours or with the daily cap used, the first batch of
  # consumed intents would close un-notified (README "Delivery gap").
  local hm; hm=$(now_hm)
  if (( 10#$hm >= 2200 || 10#$hm < 700 )); then echo "quiet_hours:$hm"; return 1; fi
  "$PY" - "$NOTIFIER_RECEIPT" <<'EOF'
import json, sys
try:
    cap = json.load(open(sys.argv[1])).get("cap") or {}
except (OSError, ValueError):
    print("notifier_receipt_unreadable"); sys.exit(1)
used, limit = cap.get("used"), cap.get("limit")
if not isinstance(used, int) or not isinstance(limit, int):
    print("notifier_cap_unknown"); sys.exit(1)
print(f"cap:{used}/{limit}:{cap.get('day')}")
sys.exit(0 if used < limit else 1)
EOF
}

ledger_report(){ "$PY" - "$LEDGER" "$LANE" "${1:-}" <<'EOF'
import os, sqlite3, sys
ledger, lane, since = sys.argv[1], sys.argv[2], sys.argv[3]
if not os.path.isfile(ledger):
    print(f"  ledger absent: {ledger}"); sys.exit(1)
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
t = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
by = dict(c.execute("SELECT state, COUNT(*) FROM comms_intents GROUP BY state")) if "comms_intents" in t else {}
print(f"  comms_intents by state: {by}")
for r in c.execute("SELECT intent_id, domain, kind, workflow_id, state, first_at FROM comms_intents"
                   " WHERE state != 'DONE' ORDER BY first_at"):
    print("    not DONE: " + " ".join(str(x) for x in r))
if "comms_intent_consumption" in t:
    print("  comms_intent_consumption by state: "
          f"{dict(c.execute('SELECT state, COUNT(*) FROM comms_intent_consumption GROUP BY state'))}")
if "comms_intent_incidents" in t:
    for r in c.execute("SELECT incident_key, fanin_item, state, count, opened_at, open_until FROM comms_intent_incidents"
                       " ORDER BY opened_at DESC LIMIT 5"):
        print("    incident: " + " ".join(str(x) for x in r))
q = "SELECT run_id, mode, state, requested_at FROM runs WHERE lane_id=?"
args = [lane]
if since:
    q += " AND requested_at >= ?"; args.append(since)
for r in c.execute(q + " ORDER BY requested_at DESC LIMIT 5", args):
    print("    run: " + " ".join(str(x) for x in r))
EOF
}

restart_units(){
  local u pid
  for u in "${UNITS[@]}"; do
    "$SYSTEMCTL_BIN" --user restart "$u.service"; sleep "${RESTART_SETTLE_S:-2}"
    pid=$("$SYSTEMCTL_BIN" --user show -p MainPID --value "$u.service")
    [[ "$pid" =~ ^[0-9]+$ && "$pid" != 0 ]] || fail "$u has no MainPID after restart"
    if [[ "${1:-}" == expect ]]; then
      if tr '\0' '\n' < "$PROC_ROOT/$pid/environ" | grep -q -- "$LANE"; then echo "  $u active, env carries $LANE"
      else fail "$u env lacks $LANE after restart"; fi
    else
      if tr '\0' '\n' < "$PROC_ROOT/$pid/environ" | grep -q -- "$LANE"; then fail "$u env still carries $LANE"; fi
      echo "  $u active, env no longer carries $LANE"
    fi
  done
}

write_live_list(){ # $1 = new space-separated list; $2 = backup tag. Backup, atomic replace, read-back.
  local new=$1 tag=$2 b
  b="$LIVE_LANES_ENV.bak-$(date -u +%Y%m%dT%H%M%SZ)-$tag"
  cp -p "$LIVE_LANES_ENV" "$b"
  "$PY" - "$LIVE_LANES_ENV" "$new" <<'EOF'
import os, sys
path, new = sys.argv[1], sys.argv[2]
lines = open(path).read().split("\n")
hits = [i for i, l in enumerate(lines) if l.startswith("TRADEAI_N8N_RELAY_LIVE_LANES=")]
assert len(hits) == 1, f"expected one TRADEAI_N8N_RELAY_LIVE_LANES= line, found {len(hits)}"
lines[hits[0]] = "TRADEAI_N8N_RELAY_LIVE_LANES=" + new
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    fh.write("\n".join(lines))
os.chmod(tmp, 0o600)
os.replace(tmp, path)
EOF
  echo "  backup $b"
}

case "$STEP" in
  pre)
    echo "  now $(now_hm) ET"
    served_state || true
    in_live_list && echo "  live list HAS $LANE" || echo "  live list lacks $LANE (relay step adds it)"
    for u in "${UNITS[@]}"; do echo "  $u: $("$SYSTEMCTL_BIN" --user is-active "$u.service" 2>/dev/null || true)"; done
    "$DOCKER_BIN" exec m8m-n8n-db psql -U n8n -d n8n -tA \
      -c "SELECT id||' active='||active::text||' updated='||\"updatedAt\"::text FROM workflow_entity WHERE id='$WID'" \
      2>/dev/null | sed 's/^/  n8n row: /' || true
    ledger_report "$SINCE" || true
    echo "  served consumer --dry-run (mode=ro, writes nothing):"
    (cd "$SERVED" && TRADEAI_STATE_ROOT="$STATE" "$PY" scripts/n8n_comms_intent_consumer.py --dry-run --ledger "$LEDGER" \
      | "$PY" -c 'import json,sys
d=json.loads(sys.stdin.read().split("DRY-RUN ",1)[1])["summary"]
print("    backlog %s deferred %s would_close %s" % (d.get("backlog"), d.get("deferred"), d.get("would_close")))
for w in d.get("would") or []:
    print("    would: %s %s/%s %s -> %s %s %s" % (w["intent_id"], w["domain"], w["kind"], w["workflow_id"],
          w["action"], w.get("severity"), w.get("fanin_item") or w.get("reason")))') || echo "    (dry run failed)"
    if w=$(delivery_window); then echo "  notifier can deliver now ($w)"
    else echo "  WARNING notifier cannot deliver a P2 now ($w): see README 'Delivery gap'"; fi ;;
  relay)
    need_grant
    served_state || fail "serve the comms consumer live PR first"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(live_lanes)
    [[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $LIVE_LANES_ENV"
    read -r -a CUR_A <<<"$CUR"
    if in_live_list; then echo "  live list already has $LANE: nothing to do"; exit 0; fi
    NEW="$CUR $LANE"
    echo "  adds: $LANE"
    echo "  keeps: ${#CUR_A[@]} existing lanes"
    if ! w=$(delivery_window); then
      [[ $APPLY == 1 ]] || echo "  WARNING --apply would be refused now: notifier cannot deliver ($w)"
      [[ $APPLY == 0 || "${ACCEPT_DELIVERY_GAP:-0}" == 1 ]] || fail "notifier cannot deliver now ($w); the first consumed intents would close un-notified. Run inside 07:00-21:59 ET with cap headroom, or set ACCEPT_DELIVERY_GAP=1"
      [[ $APPLY == 0 ]] || echo "  ACCEPT_DELIVERY_GAP=1: proceeding although the notifier cannot deliver now ($w)"
    fi
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    write_live_list "$NEW" comms-intent-consumer-live
    in_live_list || fail "READ-BACK FAILED: $LANE not in $LIVE_LANES_ENV"
    for l in "${CUR_A[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    # the gateway reads the same file (its due computation demotes a live lane missing from its env): restart BOTH
    restart_units expect ;;
  publish)
    served_state || fail "serve the comms consumer live PR first"
    SERVED="$SERVED" "$PY" - "$WID" <<'EOF' || fail "served $WID graph differs from INDEX: regenerate (build-generic) and re-import before going live"
import hashlib, json, os, sys
root, wid = os.environ["SERVED"], sys.argv[1]
d = os.path.join(root, "docs/implementation/n8n-maturity/workflows")
row = next(w for w in json.load(open(os.path.join(d, "INDEX.json")))["workflows"] if w["id"] == wid)
sha = hashlib.sha256(open(os.path.join(d, row["file"]), "rb").read()).hexdigest()
print(f"  served {row['file']} sha256 {sha} (index {row['sha256']})")
sys.exit(0 if sha == row["sha256"] else 1)
EOF
    act=$("$DOCKER_BIN" exec m8m-n8n-db psql -U n8n -d n8n -tA \
      -c "SELECT active::text FROM workflow_entity WHERE id='$WID'" 2>/dev/null || true)
    echo "  n8n $WID active=${act:-unknown}"
    [[ "$act" == true ]] || fail "$WID is not active in n8n: the lane cannot fire (activation is its own config-write act)"
    echo "  NO IMPORT NEEDED: this PR changes no workflow file (build-generic / build-fabric --check clean). The lane"
    echo "  fires through the already-active $WID once the registry row (served) and the live list (relay) say live." ;;
  proof)
    [[ -z "$SINCE" || "$SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T ]] || fail "--since must be ISO 8601 (UTC), e.g. 2026-10-17T17:30:00"
    set +e
    "$PY" - "$LEDGER" "$STATE" "$LANE" "$SINCE" <<'EOF'
import json, os, sqlite3, sys
ledger, state, lane, since = sys.argv[1:5]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
q = "SELECT run_id, state, receipt_json, requested_at FROM runs WHERE lane_id=? AND mode='live' AND run_id LIKE ?"
args = [lane, f"d:{lane}:live:%"]
if since:
    q += " AND requested_at >= ?"; args.append(since)
runs = c.execute(q + " ORDER BY requested_at", args).fetchall()
verdicts = []
for run_id, st, rj, at in runs[-6:]:
    rec = json.loads(rj) if rj else None
    if rec is None:
        p = os.path.join(state, "data", "runtime", "n8n_runs", f"{run_id}.json")
        rec = json.load(open(p)) if os.path.isfile(p) else {}
    ov = rec.get("output_verdict") or {}
    verdicts.append((st, ov.get("verdict")))
    print(f"  run {run_id}: {st} verdict={ov.get('verdict')} produced={ov.get('produced_count')} "
          f"empty_reason={ov.get('empty_reason')} skipped={ov.get('skipped_reasons')}")
done = any(st == "RUN_DONE" and v in ("produced", "empty_allowed") for st, v in verdicts)
produced = any(st == "RUN_DONE" and v == "produced" for st, v in verdicts)
bad = [r for r in runs if r[1] in ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED")]
by = dict(c.execute("SELECT state, COUNT(*) FROM comms_intents GROUP BY state"))
stale = c.execute("SELECT COUNT(*) FROM comms_intents WHERE state='QUEUED'"
                  " AND first_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', '-15 minutes')").fetchone()[0]
print(f"  comms_intents by state {by}; QUEUED older than 15 min: {stale}")
inc = c.execute("SELECT incident_key, fanin_item, state, count, opened_at FROM comms_intent_incidents"
                " WHERE opened_at >= ? ORDER BY opened_at", (since or "",)).fetchall()
for r in inc:
    print("  incident " + " ".join(str(x) for x in r))
notified = {}
try:
    notified = json.load(open(os.path.join(state, "data", "runtime", "incident_notifier_state.json"))).get("notified") or {}
except (OSError, ValueError) as exc:
    print(f"  notifier state unreadable: {type(exc).__name__}")
delivered = []
for key, item, st, n, opened in inc:
    r = notified.get(key) or {}
    ok = str(r.get("last_notified_at") or "") >= str(opened)
    delivered.append(ok)
    print(f"  notifier {key} ({item}): " + (f"DELIVERED {r.get('last_notified_at')} identity {r.get('identity')}"
                                            if ok else "NOT DELIVERED yet (P2 batch every 30 min; quiet 22-07 ET; cap 24/day)"))
fanin = {}
try:
    fanin = json.load(open(os.path.join(state, "data", "runtime", "n8n_incident_fanin_last.json")))
except (OSError, ValueError):
    pass
print(f"  fan-in {fanin.get('as_of')} comms_intent_source: {(fanin.get('source_notes') or {}).get('comms_intent_source')}")
ok_runs = done and not bad
ok_queue = stale == 0
ok_delivery = (not produced) or (bool(delivered) and all(delivered))
print(f"  live runs: {'PASS' if ok_runs else 'FAIL'} (RUN_DONE with verdict produced|empty_allowed={done}, failed={len(bad)})")
print(f"  queue drained: {'PASS' if ok_queue else 'FAIL'}")
print(f"  operator delivery: {'PASS' if ok_delivery else 'PENDING/FAIL'} (incidents since {since or 'ever'}: {len(inc)})")
sys.exit(0 if ok_runs and ok_queue and ok_delivery else 1)
EOF
    exit $? ;;
  rollback)
    # R1 (this step, config-write + service grant): the lane leaves the live list; the gateway then demotes every
    # dispatcher fire to dry_run (mode=ro, writes nothing). R2 (config): a PR that sets dispatch.mode dry_run / stage
    # shadow and live_arg null -> serve. NEVER deactivate tradeai-dispatcher: it fires every other dispatch-live lane.
    # Ledger rows stay (rail 6); an intent already consumed stays DONE; a QUEUED backlog raises the fan-in's
    # queued_stale P2 again after 2 h.
    need_grant
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    in_live_list || { echo "  live list lacks $LANE: nothing to roll back"; exit 0; }
    CUR=$(live_lanes); read -r -a CUR_A <<<"$CUR"
    KEEP=()
    for l in "${CUR_A[@]}"; do [[ "$l" == "$LANE" ]] || KEEP+=("$l"); done
    echo "  removes: $LANE; keeps ${#KEEP[@]} lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    write_live_list "${KEEP[*]}" comms-intent-consumer-rollback
    if in_live_list; then fail "READ-BACK FAILED: $LANE still in $LIVE_LANES_ENV"; fi
    for l in "${KEEP[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    restart_units absent ;;
  *) fail "usage: $0 pre|relay|publish|proof|rollback [--apply] [--since ISO]" ;;
esac
