#!/usr/bin/env bash
# Active Trader motion runtime back up, supervised by n8n. Operator decision 2026-10-19: the 5/10/30 s loop stays the
# systemd USER service tradeai-active-trader-motion.service (n8n's minimum schedule is 1 min and its runs are
# stateless), and n8n OWNS its supervision through lane active-trader-motion-watchdog (*/5, tradeai-dispatcher,
# scripts/check_active_trader_motion_heartbeat.py --apply). Dry by default; nothing here deletes anything.
#
#   bash cutover.sh pre                      read-only: installed vs served unit gate lines, unit state, marker,
#                                            heartbeat band/age (checker --dry-run), session state, live list
#   bash cutover.sh marker                   read-only: prints the OPERATOR-ONLY sudo command; never runs it
#   bash cutover.sh install  [--apply]       archive the installed unit (copy .archived-<UTC>), install the served
#                                            fixed unit to ~/.config/systemd/user, read back, daemon-reload. No start
#   bash cutover.sh start    [--apply]       systemctl --user restart (starts the inactive unit). Refused unless the
#                          [--force-open-hours]  marker exists, the fixed unit is installed and the market session is
#                                            CLOSED (AGENTS.md §24.10: pre/post-market count as open; a calendar
#                                            error refuses). --force-open-hours is the OPERATOR's override only
#   bash cutover.sh proof                    read-only: heartbeat updated within 60 s, cycle_count increasing,
#                                            journal growing, pid alive, status healthy, authority all false
#   bash cutover.sh relay    [--apply]       watchdog lane -> TRADEAI_N8N_RELAY_LIVE_LANES; backup + read-back;
#                                            restart relay AND gateway (they read the live list)
#   bash cutover.sh rollback [--apply]       watchdog lane leaves the live list (backup + read-back; restart relay
#                                            AND gateway); prints, never runs, the operator-only motion-unit rollback
#
# Order: merge + promote (CURRENT serves the PR) -> pre -> marker (operator, sudo) -> install --apply -> after the
# session closes: start --apply -> proof -> relay --apply -> one */5 slot -> pre (band HEALTHY in the watchdog state).
# TRADEAI_FABRIC_GRANT is required for every --apply and must be the id of an ACTIVE guard grant
# (TRADEAI_FABRIC_GRANT=$(bin/guard id config-write)); a free-text label is refused (scripts/lib/fabric_grant.py,
# read-only ledger check, consumes no use). install/start accept a config-write or execution-ops grant; relay/rollback a
# config-write or cron grant.
# This script never touches a broker, an order, a credential, an EnvironmentFile, the crontab or an n8n workflow, and
# never runs sudo, stop, kill, enable, disable or mask.
# Test hooks (hermetic tests only): SYSTEMCTL_BIN, PROC_ROOT, UNIT_DIR, MARKER, HEARTBEAT, NOW_ISO, PROOF_GAP_S,
# RESTART_SETTLE_S, GUARD_APPROVALS_DIR (read by fabric_grant.py).
set -euo pipefail
set -f
CODE=$(cd "$(dirname "$0")/../../../.." && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
GRANT_PY=${GRANT_PY:-$CODE/scripts/lib/fabric_grant.py}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
UNIT_DIR=${UNIT_DIR:-$HOME/.config/systemd/user}
MARKER=${MARKER:-/etc/tradeai/enable-active-trader-motion}
HEARTBEAT=${HEARTBEAT:-$REPO/data/active_trader/motion_runtime_heartbeat.json}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
PROC_ROOT=${PROC_ROOT:-/proc}
PROOF_GAP_S=${PROOF_GAP_S:-35}
UNIT=tradeai-active-trader-motion.service
LANE=active-trader-motion-watchdog
GATE_LINE="ConditionPathExists=/etc/tradeai/enable-active-trader-motion"
TYPO_DIR="/etc/tar""deai"   # the misspelt directory of the 2026-10-10 install, split so a repo grep stays clean
RELAY_UNITS=(tradeai-n8n-run-relay tradeai-n8n-coordination-gateway)
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=${1:-}; shift || true
APPLY=0; FORCE_OPEN=0
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --force-open-hours) FORCE_OPEN=1; shift ;; *) fail "unknown arg $1" ;; esac
done
# The value must be the id of an ACTIVE guard grant of one of $1's tiers; a free-text label is refused. Read-only.
need_grant(){
  [[ $APPLY == 0 ]] && return 0
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
  local hit
  hit=$("$PY" "$GRANT_PY" verify "$TRADEAI_FABRIC_GRANT" "$1") || fail "TRADEAI_FABRIC_GRANT is not an active $1 grant id (bin/guard id ${1%%,*})"
  echo "  grant ok: $hit"
}
FRAG="$UNIT_DIR/$UNIT"
SRC="$SERVED/config/systemd/$UNIT"
gate_lines(){ grep -E '^(ConditionPathExists|EnvironmentFile)=' "$1" | sed 's/^/    /' || echo "    (no gate lines)"; }
unit_fixed(){ [[ -f "$1" ]] && grep -qx -- "$GATE_LINE" "$1" && ! grep -qF -- "$TYPO_DIR" "$1"; }
live_lanes(){ sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV"; }
in_live_list(){ [[ -f "$LIVE_LANES_ENV" ]] && live_lanes | tr ' ' '\n' | grep -qx -- "$LANE"; }

session_state(){ # prints the NYSE session state (PRE|RTH|POST|CLOSED) from the repo calendar; exit 1 on error
  NOW_ISO="${NOW_ISO:-}" "$PY" - "$CODE" <<'EOF'
import os, sys
from datetime import datetime, timezone
sys.path.insert(0, sys.argv[1])
try:
    from scripts.lib import cio_market_session as M
    raw = os.environ.get("NOW_ISO") or ""
    now = datetime.fromisoformat(raw.replace("Z", "+00:00")) if raw else datetime.now(timezone.utc)
    s = M.NYSESessionService().session_at(now)
    print(f"{s['state']} {s['session_date']} trading_day={s['is_trading_day']}")
except Exception as exc:  # the caller fails closed
    print(f"calendar_error:{type(exc).__name__}")
    sys.exit(1)
EOF
}

watchdog_dry(){ # the checker's verdict against the real heartbeat, marker and /proc; writes nothing
  (cd "$CODE" && "$PY" scripts/check_active_trader_motion_heartbeat.py --dry-run --heartbeat "$HEARTBEAT" \
      --marker "$MARKER" --proc-root "$PROC_ROOT" --state-root "$STATE" ${NOW_ISO:+--now "$NOW_ISO"} \
    | "$PY" -c 'import json,sys
d=json.loads(sys.stdin.read().split("DRY-RUN ",1)[1])["summary"]
v, w = d.get("verdict") or {}, d.get("window") or {}
print("    band %s (%s) age %ss status %s cycles %s pid %s %s marker %s" % (v.get("band"), "; ".join(v.get("reasons") or []),
      v.get("heartbeat_age_s"), v.get("status"), v.get("cycle_count"), v.get("pid"), v.get("pid_state"), v.get("marker_present")))
print("    window %s (%s); last alerted band %s; would action %s" % (w.get("in_window"), w.get("reason"),
      d.get("previous_alerted_band"), d.get("action")))') || echo "    (watchdog dry run failed)"
}

served_lane(){ # the served watchdog wiring; exit 1 unless the PR is served
  SERVED="$SERVED" "$PY" - "$LANE" <<'EOF'
import json, os, sys
root, lane = os.environ["SERVED"], sys.argv[1]
j = lambda rel: json.load(open(os.path.join(root, rel)))
try:
    reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}.get(lane) or {}
    allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}.get(lane) or {}
    hc = {c["id"]: c for c in j("config/n8n_health_contracts.json")["contracts"]}.get(lane) or {}
    routes = j("config/host_comms_intent_routes.json")["routes"]
except (OSError, ValueError) as exc:
    print(f"  served config unreadable: {type(exc).__name__}"); sys.exit(1)
sched, disp = reg.get("scheduler") or {}, reg.get("dispatch") or {}
checks = {
    "registry scheduler n8n/dispatcher stage canary": (sched.get("kind"), sched.get("expression"), sched.get("stage"))
    == ("n8n", "dispatcher", "canary"),
    "registry dispatch live */5": disp.get("mode") == "live" and disp.get("cron") == ["*/5 * * * *"],
    "allowlist live_arg --apply, output_receipt v2": allow.get("live_arg") == ["--apply"] and allow.get("output_receipt") == "v2",
    "health contract REVIEWED canary empty_allowed": hc.get("status") == "REVIEWED" and hc.get("stage") == "canary"
    and (hc.get("expected_output") or {}).get("rule") == "empty_allowed",
    "host route host/active_trader_motion_watchdog": any(r.get("kind") == "active_trader_motion_watchdog" for r in routes),
    "checker present": os.path.isfile(os.path.join(root, "scripts/check_active_trader_motion_heartbeat.py")),
}
for name, good in checks.items():
    print(f"  {'ok ' if good else 'BAD'} {name}")
ok = all(checks.values())
print(f"  served {os.path.basename(root)}: " + ("WATCHDOG PR SERVED" if ok else "PR NOT served (merge, then promote): stop here"))
sys.exit(0 if ok else 1)
EOF
}

restart_relay_units(){
  local u pid
  for u in "${RELAY_UNITS[@]}"; do
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

write_live_list(){ # $1 = new space-separated list; $2 = backup tag. Backup, atomic replace, read-back by the caller.
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
    echo "  now ${NOW_ISO:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}; session $(session_state || true)"
    echo "  installed unit $FRAG:"
    if [[ -f "$FRAG" ]]; then gate_lines "$FRAG"; else echo "    (absent)"; fi
    if unit_fixed "$FRAG"; then echo "  installed unit: FIXED (marker under /etc/tradeai)"
    else echo "  installed unit: NOT fixed (install step replaces it)"; fi
    echo "  served unit $SRC:"
    if [[ -f "$SRC" ]]; then gate_lines "$SRC"; else echo "    (absent)"; fi
    echo "  $UNIT: $("$SYSTEMCTL_BIN" --user is-active "$UNIT" 2>/dev/null || true)"
    if [[ -e "$MARKER" ]]; then echo "  marker $MARKER: PRESENT"; else echo "  marker $MARKER: ABSENT (operator step: bash cutover.sh marker)"; fi
    echo "  watchdog --dry-run (writes nothing):"
    watchdog_dry
    if in_live_list; then echo "  live list HAS $LANE"; else echo "  live list lacks $LANE (relay step adds it)"; fi
    served_lane || true ;;
  marker)
    if [[ -e "$MARKER" ]]; then echo "  marker $MARKER: PRESENT (nothing to do)"; exit 0; fi
    echo "  marker $MARKER: ABSENT. OPERATOR-ONLY (root; AGENTS.md §24.10 item 4 keeps an /etc flag operator-only)."
    echo "  Run it yourself; this script never runs sudo:"
    echo ""
    echo "      sudo touch $MARKER"
    echo "" ;;
  install)
    need_grant config-write,execution-ops
    unit_fixed "$SRC" || fail "served unit $SRC does not carry $GATE_LINE: merge + promote the PR first"
    if unit_fixed "$FRAG" && cmp -s "$SRC" "$FRAG"; then echo "  installed unit already equals the served fixed unit: nothing to do"; exit 0; fi
    echo "  replaces $FRAG with $SRC"
    if [[ -f "$FRAG" ]]; then diff -u "$FRAG" "$SRC" | sed 's/^/    /' || true; fi
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — unit file unchanged, no daemon-reload"; exit 0; }
    if [[ -f "$FRAG" ]]; then
      b="$FRAG.archived-$(date -u +%Y%m%dT%H%M%SZ)"
      cp -p "$FRAG" "$b"; echo "  archived $b"
    fi
    install -m 0644 "$SRC" "$FRAG"
    cmp -s "$SRC" "$FRAG" || fail "READ-BACK FAILED: $FRAG differs from $SRC"
    unit_fixed "$FRAG" || fail "READ-BACK FAILED: $FRAG lacks $GATE_LINE"
    "$SYSTEMCTL_BIN" --user daemon-reload
    echo "  installed + daemon-reload; the unit is NOT started (start step, after the session closes)" ;;
  start)
    need_grant config-write,execution-ops
    [[ -e "$MARKER" ]] || fail "marker $MARKER absent: the operator creates it first (bash cutover.sh marker)"
    unit_fixed "$FRAG" || fail "installed unit is not the fixed one: bash cutover.sh install --apply first"
    if ! s=$(session_state); then fail "market calendar error ($s): refusing (fails closed)"; fi
    if [[ "${s%% *}" != CLOSED ]]; then
      [[ $FORCE_OPEN == 1 ]] || fail "market session is ${s%% *} ($s): start only while CLOSED (20:00-04:00 ET on trading days, weekends, holidays; AGENTS.md §24.10), or the operator passes --force-open-hours"
      echo "  WARNING --force-open-hours: starting while the session is ${s%% *}. Operator override only; never under an agent's execution-ops grant"
    fi
    echo "  session $s"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — would run: systemctl --user restart $UNIT"; exit 0; }
    "$SYSTEMCTL_BIN" --user restart "$UNIT"; sleep "${RESTART_SETTLE_S:-3}"
    act=$("$SYSTEMCTL_BIN" --user is-active "$UNIT" 2>/dev/null || true)
    pid=$("$SYSTEMCTL_BIN" --user show -p MainPID --value "$UNIT")
    [[ "$act" == active && "$pid" =~ ^[0-9]+$ && "$pid" != 0 ]] || fail "$UNIT not active after restart (is-active=$act MainPID=$pid): see journalctl --user -u $UNIT"
    echo "  $UNIT active, MainPID $pid. Next: bash cutover.sh proof" ;;
  proof)
    set +e
    "$PY" - "$HEARTBEAT" "$PROC_ROOT" "$PROOF_GAP_S" <<'EOF'
import json, os, sys, time
hb_path, proc_root, gap = sys.argv[1], sys.argv[2], float(sys.argv[3])
def sample():
    try:
        d = json.load(open(hb_path))
    except (OSError, ValueError) as exc:
        return None, f"heartbeat unreadable: {type(exc).__name__}"
    j = d.get("journal_path") or ""
    try:
        st = os.stat(j); js = (st.st_size, st.st_mtime)
    except OSError:
        js = None
    return {"doc": d, "journal": js, "at": time.time()}, None
a, err = sample()
if a is None:
    print(f"  FAIL {err}"); sys.exit(1)
print(f"  sample 1: cycle_count {a['doc'].get('cycle_count')} pid {a['doc'].get('pid')}; waiting {gap:.0f}s")
time.sleep(gap)
b, err = sample()
if b is None:
    print(f"  FAIL {err}"); sys.exit(1)
d = b["doc"]
age = b["at"] - float(d.get("updated_at") or 0)
pid = d.get("pid")
checks = {
    "contract active-trader-motion-runtime-heartbeat-v1": d.get("contract") == "active-trader-motion-runtime-heartbeat-v1",
    f"heartbeat updated within 60 s (age {age:.1f}s)": 0 <= age <= 60,
    f"cycle_count increasing ({a['doc'].get('cycle_count')} -> {d.get('cycle_count')})":
        isinstance(d.get("cycle_count"), int) and isinstance(a["doc"].get("cycle_count"), int)
        and d["cycle_count"] > a["doc"]["cycle_count"],
    f"journal growing ({a['journal']} -> {b['journal']})": a["journal"] is not None and b["journal"] is not None
        and (b["journal"][0] != a["journal"][0] or b["journal"][1] > a["journal"][1]),
    f"pid {pid} alive": isinstance(pid, int) and os.path.isdir(os.path.join(proc_root, str(pid))),
    f"status healthy ({d.get('status')})": d.get("status") == "healthy",
    "authority all false": isinstance(d.get("authority"), dict) and bool(d["authority"])
        and all(v is False for v in d["authority"].values()),
}
for name, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'} {name}")
ok = all(checks.values())
print(f"  proof: {'PASS' if ok else 'FAIL'}")
sys.exit(0 if ok else 1)
EOF
    exit $? ;;
  relay)
    need_grant config-write,cron
    served_lane || fail "serve the watchdog PR first"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(live_lanes)
    [[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $LIVE_LANES_ENV"
    read -r -a CUR_A <<<"$CUR"
    if in_live_list; then echo "  live list already has $LANE: nothing to do"; exit 0; fi
    echo "  adds: $LANE"
    echo "  keeps: ${#CUR_A[@]} existing lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    write_live_list "$CUR $LANE" motion-watchdog-live
    in_live_list || fail "READ-BACK FAILED: $LANE not in $LIVE_LANES_ENV"
    for l in "${CUR_A[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    restart_relay_units expect ;;
  rollback)
    # R1 (this step): the watchdog leaves the live list; the gateway then demotes every dispatcher fire to dry_run
    # (prints, writes nothing). The motion unit is NOT touched here: stopping it or archiving the /etc marker is the
    # operator's (AGENTS.md §24.10: stop and sudo are outside execution-ops). Commands are printed below.
    need_grant config-write,cron
    echo "  operator-only motion rollback (printed, never run):"
    echo "      systemctl --user stop $UNIT"
    echo "      sudo mv $MARKER $MARKER.archived-\$(date +%Y%m%d)"
    echo "      # previous unit copy: $FRAG.archived-<UTC> (install step); restore with cp -p + systemctl --user daemon-reload"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    in_live_list || { echo "  live list lacks $LANE: nothing to roll back"; exit 0; }
    CUR=$(live_lanes); read -r -a CUR_A <<<"$CUR"
    KEEP=()
    for l in "${CUR_A[@]}"; do [[ "$l" == "$LANE" ]] || KEEP+=("$l"); done
    echo "  removes: $LANE; keeps ${#KEEP[@]} lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    write_live_list "${KEEP[*]}" motion-watchdog-rollback
    if in_live_list; then fail "READ-BACK FAILED: $LANE still in $LIVE_LANES_ENV"; fi
    for l in "${KEEP[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    restart_relay_units absent ;;
  *) fail "usage: $0 pre|marker|install|start|proof|relay|rollback [--apply] [--force-open-hours]" ;;
esac
