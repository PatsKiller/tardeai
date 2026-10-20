#!/usr/bin/env bash
# Data-integrity monitors on the n8n fabric (operator 2026-10-18: one data-integrity fix PR, the two monitors "within
# n8n with proper contracts"). Cutover standard 2026-10-14: fix + dry run + regression + >=1 live n8n run, no soak.
# Dry by default; nothing here deletes anything, and this script NEVER changes a systemd unit: every state-changing
# systemctl command (relay/gateway restart, timer disable/enable) is PRINTED for the operator to run.
#
# Lanes (n8n-native dispatcher rows, stage canary, the systemd timers' own cadence; entry scripts run the monitors'
# lane_main, which never references the chokepoint send):
#   n8n-data-plausibility-audit  scripts/n8n_data_plausibility_audit.py  20 6 * * *    (tradeai-data-plausibility.timer)
#   n8n-gap-resolution-audit     scripts/n8n_gap_resolution_audit.py     7,37 * * * *  (tradeai-gap-resolution.timer)
# CANARY with a DRY live_arg first: [] (measure + LaneRunReceipt@v2, notify nobody). The systemd timers stay the
# alerting owners until c3. c3 needs a follow-up PR that sets the allowlist live_arg to ["--alert"] (queues a host
# comms intent; never a sender) — c3 refuses until it is served.
#
#   bash cutover.sh pre                     read-only: served PR state, live list, timer state, ledger runs, a served
#                                           --dry-run of both monitors
#   bash cutover.sh relay    [--apply]      live list += both lanes; backup + atomic replace + read-back
#                                           (config-write grant); PRINTS the relay + gateway restart commands
#   bash cutover.sh proof [--since ISO]     read-only: >=1 live RUN_DONE per lane with output verdict
#                                           produced|empty_allowed, and each lane's LaneRunReceipt ok
#   bash cutover.sh c3       [--apply]      owner switch: refuses unless the served live_arg is ["--alert"],
#                                           both lanes are in the live list and proof passes;
#                                           --apply records the switch receipt and PRINTS the timer-disable commands
#   bash cutover.sh rollback [--apply]      live list -= both lanes (backup + read-back); PRINTS the restart commands
#                                           and the timer re-enable commands (if c3 ran)
#
# Order: (merge + promote the PR so CURRENT serves it) -> pre -> relay --apply -> (operator: restart relay + gateway)
# -> wait one slot per lane -> proof -> (follow-up PR: live_arg ["--alert"]; promote) -> proof -> c3.
# TRADEAI_FABRIC_GRANT (the config-write grant id) is required for every --apply.
# This script never touches a broker, an order, a secret value, the crontab, a systemd unit or an n8n workflow.
# Test hooks (hermetic tests only): SYSTEMCTL_BIN (read-only queries only), PROC_ROOT.
set -euo pipefail
set -f
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER=${LEDGER:-$STATE/data/governance/n8n_coordination_ledger.sqlite}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
SWITCH_RECEIPT=${SWITCH_RECEIPT:-$STATE/data/runtime/data_integrity_monitors_owner_switch.json}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
LANES=(n8n-data-plausibility-audit n8n-gap-resolution-audit)
TIMERS=(tradeai-data-plausibility.timer tradeai-gap-resolution.timer)
UNITS=(tradeai-n8n-run-relay tradeai-n8n-coordination-gateway)
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=${1:-}; shift || true
APPLY=0; SINCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --since) SINCE=${2:-}; shift 2 ;; *) fail "unknown arg $1" ;; esac
done
need_grant(){ [[ $APPLY == 0 || -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"; }
live_lanes(){ sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV"; }
in_live_list(){ [[ -f "$LIVE_LANES_ENV" ]] && live_lanes | tr ' ' '\n' | grep -qx -- "$1"; }
print_restart(){
  echo "  OPERATOR (service grant) — the relay and the gateway read the live list at start; restart BOTH:"
  local u
  for u in "${UNITS[@]}"; do echo "    systemctl --user restart $u.service"; done
}

served_state(){ # the served data-integrity facts; $1 = "owner" also requires the owner-switch live_arg
  SERVED="$SERVED" "$PY" - "${1:-canary}" "${LANES[@]}" <<'EOF'
import json, os, sys
root, want, lanes = os.environ["SERVED"], sys.argv[1], sys.argv[2:]
j = lambda rel: json.load(open(os.path.join(root, rel)))
reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}
allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}
hc = {c["id"]: c for c in j("config/n8n_health_contracts.json")["contracts"]}
routes = {(r["domain"], r["kind"]) for r in j("config/host_comms_intent_routes.json")["routes"]}
owner_arg = ["--alert"]
checks = {}
for lane in lanes:
    r, a, c = reg.get(lane) or {}, allow.get(lane) or {}, hc.get(lane) or {}
    sched, disp = r.get("scheduler") or {}, r.get("dispatch") or {}
    checks[f"{lane}: registry n8n/dispatcher canary + dispatch live"] = (
        (sched.get("kind"), sched.get("expression"), sched.get("stage"), disp.get("mode"))
        == ("n8n", "dispatcher", "canary", "live"))
    checks[f"{lane}: allowlist dry_run_arg --dry-run + output_receipt v2"] = (
        a.get("dry_run_arg") == ["--dry-run"] and a.get("output_receipt") == "v2")
    if want == "owner":
        checks[f"{lane}: allowlist live_arg = owner-switch argv {' '.join(owner_arg)}"] = a.get("live_arg") == owner_arg
    else:
        checks[f"{lane}: allowlist live_arg set"] = isinstance(a.get("live_arg"), list)
    checks[f"{lane}: health contract REVIEWED canary + expected_output"] = (
        c.get("status") == "REVIEWED" and c.get("stage") == "canary" and bool(c.get("expected_output")))
checks["host intent routes data/* present"] = {("data", "data_plausibility_violation"),
    ("data", "gap_resolution_finding"), ("data", "gap_resolution_digest")} <= routes
for name, good in checks.items():
    print(f"  {'ok ' if good else 'BAD'} {name}")
ok = all(checks.values())
print(f"  served {os.path.basename(root)}: " + ("DATA-INTEGRITY MONITORS PR SERVED" + (" (owner-switch argv)" if want == "owner" else "")
      if ok else "PR NOT served as required (merge, then promote): stop here"))
sys.exit(0 if ok else 1)
EOF
}

ledger_proof(){ # >=1 live RUN_DONE with verdict produced|empty_allowed for EVERY lane (since $1)
  "$PY" - "$LEDGER" "$STATE" "${1:-}" "${LANES[@]}" <<'EOF'
import json, os, sqlite3, sys
ledger, state, since, lanes = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
if not os.path.isfile(ledger):
    print(f"  ledger absent: {ledger}"); sys.exit(1)
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
all_ok = True
for lane in lanes:
    q = "SELECT run_id, state, receipt_json, requested_at FROM runs WHERE lane_id=? AND mode='live'"
    args = [lane]
    if since:
        q += " AND requested_at >= ?"; args.append(since)
    runs = c.execute(q + " ORDER BY requested_at", args).fetchall()
    good = 0
    for run_id, st, rj, at in runs[-6:]:
        rec = json.loads(rj) if rj else {}
        ov = rec.get("output_verdict") or {}
        print(f"  {lane} run {run_id}: {st} verdict={ov.get('verdict')} produced={ov.get('produced_count')} "
              f"empty_reason={ov.get('empty_reason')} skipped={ov.get('skipped_reasons')}")
        good += st == "RUN_DONE" and ov.get("verdict") in ("produced", "empty_allowed")
    bad = sum(1 for r in runs if r[1] in ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED"))
    receipt = os.path.join(state, "data", "runtime", f"{lane}_last.json")
    try:
        doc = json.load(open(receipt))
        rec_ok = doc.get("status") == "ok"
        print(f"  {lane} receipt status={doc.get('status')} ok_at={doc.get('ok_at')} summary={doc.get('summary')}")
    except (OSError, ValueError):
        rec_ok = False
        print(f"  {lane} receipt missing/unreadable: {receipt}")
    ok = good >= 1 and bad == 0 and rec_ok
    all_ok &= ok
    print(f"  {lane}: {'PASS' if ok else 'FAIL'} (good live runs={good}, failed={bad}, receipt ok={rec_ok})")
sys.exit(0 if all_ok else 1)
EOF
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
    served_state || true
    for l in "${LANES[@]}"; do
      if in_live_list "$l"; then echo "  live list HAS $l"; else echo "  live list lacks $l (relay step adds it)"; fi
    done
    for t in "${TIMERS[@]}"; do  # read-only queries
      echo "  $t: enabled=$("$SYSTEMCTL_BIN" --user is-enabled "$t" 2>/dev/null || true)" \
           "active=$("$SYSTEMCTL_BIN" --user is-active "$t" 2>/dev/null || true)"
    done
    [[ -f "$SWITCH_RECEIPT" ]] && echo "  owner switch recorded: $SWITCH_RECEIPT" || echo "  owner switch: not recorded (timers own alerting)"
    ledger_proof "$SINCE" || true
    echo "  served --dry-run (read-only; writes nothing):"
    (cd "$SERVED" && "$PY" scripts/data_plausibility_monitor.py --dry-run | tail -3) || echo "    (plausibility dry run: findings or failure, see above)"
    (cd "$SERVED" && "$PY" scripts/check_gap_resolution.py --dry-run | tail -3) || echo "    (gap dry run: findings or failure, see above)" ;;
  relay)
    need_grant
    served_state || fail "serve the data-integrity monitors PR first"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(live_lanes)
    [[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $LIVE_LANES_ENV"
    read -r -a CUR_A <<<"$CUR"
    ADD=()
    for l in "${LANES[@]}"; do in_live_list "$l" || ADD+=("$l"); done
    if [[ ${#ADD[@]} == 0 ]]; then echo "  live list already has both lanes: nothing to do"; exit 0; fi
    echo "  adds: ${ADD[*]}"
    echo "  keeps: ${#CUR_A[@]} existing lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged"; print_restart; exit 0; }
    write_live_list "$CUR ${ADD[*]}" data-integrity-monitors-relay
    for l in "${LANES[@]}"; do in_live_list "$l" || fail "READ-BACK FAILED: $l not in $LIVE_LANES_ENV"; done
    for l in "${CUR_A[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    print_restart ;;
  proof)
    [[ -z "$SINCE" || "$SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T ]] || fail "--since must be ISO 8601 (UTC), e.g. 2026-10-18T10:30:00"
    ledger_proof "$SINCE" ;;
  c3)
    # Owner switch. The n8n lane becomes the alerting owner; the systemd timer must stop so the operator is not told
    # twice. This script only RECORDS the switch and PRINTS the timer commands: it never runs a state-changing
    # systemctl verb (operator 2026-10-18).
    need_grant
    served_state owner || fail "the served allowlist live_arg is not the owner-switch argv [--alert]: land and promote the follow-up PR first"
    for l in "${LANES[@]}"; do in_live_list "$l" || fail "$l not in the live list: run relay first"; done
    ledger_proof "$SINCE" || fail "no proven live n8n run for both lanes (proof): the timers keep alerting"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — no switch recorded; would print:"; for t in "${TIMERS[@]}"; do echo "    systemctl --user disable --now $t"; done; exit 0; }
    mkdir -p "$(dirname "$SWITCH_RECEIPT")"
    "$PY" - "$SWITCH_RECEIPT" "${TRADEAI_FABRIC_GRANT}" "${LANES[*]}" "${TIMERS[*]}" <<'EOF'
import json, os, sys
from datetime import datetime, timezone
path, grant, lanes, timers = sys.argv[1], sys.argv[2], sys.argv[3].split(), sys.argv[4].split()
doc = {"schema": "DataIntegrityOwnerSwitch@v1", "switched_at": datetime.now(timezone.utc).isoformat(),
       "grant": grant, "owner": "n8n", "lanes": lanes, "retired_timers": timers,
       "operator_commands": [f"systemctl --user disable --now {t}" for t in timers],
       "rollback": "bash docs/ops/packets/data-integrity-monitors-n8n-20261018/cutover.sh rollback --apply"}
tmp = path + ".tmp"
with open(tmp, "w") as fh:
    json.dump(doc, fh, indent=1)
os.replace(tmp, path)
print(f"  owner switch recorded: {path}")
EOF
    echo "  OPERATOR — retire the timers now (the n8n lanes alert from here on); verify with is-enabled = disabled:"
    for t in "${TIMERS[@]}"; do echo "    systemctl --user disable --now $t"; done
    echo "  then a registry PR marks lanes data-plausibility-audit / gap-resolution-audit RETIRED (timer disabled)." ;;
  rollback)
    # R1 (config-write grant): both lanes leave the live list; the gateway then demotes every dispatcher fire to
    # dry_run (--dry-run: writes nothing). R2: if c3 ran, the operator re-enables the timers (printed). R3 (config): a
    # PR that sets dispatch.mode dry_run / stage shadow and live_arg null -> serve. The switch receipt stays (rail 6).
    need_grant
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(live_lanes); read -r -a CUR_A <<<"$CUR"
    KEEP=()
    for l in "${CUR_A[@]}"; do
      case " ${LANES[*]} " in *" $l "*) ;; *) KEEP+=("$l") ;; esac
    done
    if [[ ${#KEEP[@]} == "${#CUR_A[@]}" ]]; then echo "  live list lacks both lanes: nothing to roll back in the list"
    else
      echo "  removes: ${LANES[*]}; keeps ${#KEEP[@]} lanes"
      if [[ $APPLY == 1 ]]; then
        write_live_list "${KEEP[*]}" data-integrity-monitors-rollback
        for l in "${LANES[@]}"; do if in_live_list "$l"; then fail "READ-BACK FAILED: $l still in $LIVE_LANES_ENV"; fi; done
        for l in "${KEEP[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
      else
        echo "  DRY RUN — live list unchanged"
      fi
      print_restart
    fi
    if [[ -f "$SWITCH_RECEIPT" ]]; then
      echo "  OPERATOR — c3 ran ($SWITCH_RECEIPT): re-enable the timers so the host alerts again:"
      for t in "${TIMERS[@]}"; do echo "    systemctl --user enable --now $t"; done
    fi ;;
  *) fail "usage: $0 pre|relay|proof|c3|rollback [--apply] [--since ISO]" ;;
esac
