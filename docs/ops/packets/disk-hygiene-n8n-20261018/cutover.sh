#!/usr/bin/env bash
# Disk hygiene + disk-usage monitor on the n8n fabric. Operator 2026-10-18: "a script with rules that's repeatable,
# n8n should run this weekly; and also monitor when a threshold is over 80%, fix and move to n8n where monitored."
# Cutover standard 2026-10-14: fix + dry run + regression + >=1 live n8n run, no soak. Dry by default.
#
# Lanes (n8n-native, fired by the already-active tradeai-dispatcher; no cron line or unit ever existed):
#   disk-usage-monitor  */15        scripts/disk_usage_monitor.py --apply  (bands; one host comms intent per band change)
#   disk-hygiene        Sun 04:00   scripts/disk_hygiene.py --plan         (manifest only: DELETES NOTHING)
#   tmp-hygiene         daily 05:00 scripts/tmp_hygiene.py --plan          (/tmp manifest with inodes: DELETES NOTHING)
# 2026-10-19 (operator, after /tmp, a tmpfs, hit 97% INODES with 20G bytes free and tools failed with ENOSPC): the
# monitor also bands inode use per mount (/ and /tmp), and tmp-hygiene plans the /tmp reclaim (ended Claude session
# scratch dirs, old pytest temp; every other /tmp entry is never touched).
# Until a lane is in TRADEAI_N8N_RELAY_LIVE_LANES the gateway demotes its fire to dry_run (prints only).
#
#   bash cutover.sh pre                     read-only: served PR state, live list, units, dispatcher row, served dry
#                                           runs of both scripts (monitor bands; hygiene plan without sizes)
#   bash cutover.sh dry-manifest [--apply]  hygiene plan WITH sizes + human summary. Dry: --dry-run (writes nothing).
#                                           --apply: --plan, writes the manifest + receipt under $STATE (deletes nothing)
#   bash cutover.sh relay    [--apply]      live list += all three lanes; backup + read-back; restart relay AND gateway
#                                           (config-write + service grant: TRADEAI_FABRIC_GRANT)
#   bash cutover.sh publish                 read-only: NO import needed; served tradeai-dispatcher.json == INDEX, active
#   bash cutover.sh proof [--since ISO]     read-only: live RUN_DONE runs with verdict produced for every lane, the
#                                           monitor state file, the latest manifest, and that its items still exist
#   bash cutover.sh backstop                PRINT ONLY: the operator commands that move the systemd
#                                           disk_pressure_guard to a 95% host backstop (never run by this script)
#   bash cutover.sh hygiene-apply [--apply] OPERATOR ONLY, after reviewing the manifest: dry prints the latest
#                                           manifest's counts; --apply needs TRADEAI_DISK_HYGIENE_GRANT and runs
#                                           disk_hygiene.py --apply (re-validates every item, caps from config)
#   bash cutover.sh tmp-dry                 read-only: tmp_hygiene.py --dry-run --report against the real /tmp
#                                           (writes nothing; prints candidates, inodes / bytes reclaimable, exclusions)
#   bash cutover.sh tmp-apply [--apply]     OPERATOR ONLY, after reviewing the /tmp manifest: dry prints its counts;
#                                           --apply needs TRADEAI_DISK_HYGIENE_GRANT and runs tmp_hygiene.py --apply
#   bash cutover.sh rollback [--apply]      live list -= all three lanes (backup + read-back); restart relay AND gateway.
#                                           NEVER deactivates tradeai-dispatcher (it fires every other live lane)
#
# Order: (merge + promote so CURRENT serves the PR) -> pre -> dry-manifest -> relay --apply -> publish -> wait one
# */15 slot -> proof. The weekly hygiene lane first fires Sunday 04:00 ET; the operator reviews that manifest before
# any hygiene-apply. This script never touches a broker, an order, a secret value, the crontab or an n8n workflow,
# and never runs systemctl except the relay/gateway restarts of relay/rollback --apply.
# Test hooks (hermetic tests only): SYSTEMCTL_BIN, DOCKER_BIN, PROC_ROOT, HYGIENE_EXTRA (extra disk_hygiene.py args).
set -euo pipefail
set -f
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER=${LEDGER:-$STATE/data/governance/n8n_coordination_ledger.sqlite}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
DOCKER_BIN=${DOCKER_BIN:-docker}
PROC_ROOT=${PROC_ROOT:-/proc}
HYGIENE_EXTRA=${HYGIENE_EXTRA:-}
LANES=(disk-usage-monitor disk-hygiene tmp-hygiene)
WID=tradeai-dispatcher
UNITS=(tradeai-n8n-run-relay tradeai-n8n-coordination-gateway)
GUARD_UNIT=tradeai-disk-pressure-guard
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=${1:-}; shift || true
APPLY=0; SINCE=""
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --since) SINCE=${2:-}; shift 2 ;; *) fail "unknown arg $1" ;; esac
done
need_grant(){ [[ $APPLY == 0 || -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"; }
live_lanes(){ sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV"; }
in_live_list(){ [[ -f "$LIVE_LANES_ENV" ]] && live_lanes | tr ' ' '\n' | grep -qx -- "$1"; }
read -r -a EXTRA_A <<<"$HYGIENE_EXTRA"

served_state(){ # the served disk-hygiene-n8n facts; exit 1 unless the PR is served
  SERVED="$SERVED" "$PY" - <<'EOF'
import json, os, sys
root = os.environ["SERVED"]
j = lambda rel: json.load(open(os.path.join(root, rel)))
reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}
allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}
hc = {c["id"]: c for c in j("config/n8n_health_contracts.json")["contracts"]}
routes = {(r["domain"], r["kind"]) for r in j("config/host_comms_intent_routes.json")["routes"]}
want = {"disk-usage-monitor": (["*/15 * * * *"], ["--apply"]), "disk-hygiene": (["0 4 * * 0"], ["--plan"]),
        "tmp-hygiene": (["0 5 * * *"], ["--plan"])}
checks = {}
for lane, (cron, live_arg) in want.items():
    r, a, c = reg.get(lane) or {}, allow.get(lane) or {}, hc.get(lane) or {}
    s, d = r.get("scheduler") or {}, r.get("dispatch") or {}
    checks[f"{lane}: registry n8n/dispatcher canary, dispatch live {cron[0]}"] = (
        (s.get("kind"), s.get("expression"), s.get("stage")) == ("n8n", "dispatcher", "canary")
        and d.get("mode") == "live" and d.get("cron") == cron)
    checks[f"{lane}: allowlist live_arg {live_arg}, output_receipt v2"] = (
        a.get("live_arg") == live_arg and a.get("output_receipt") == "v2")
    checks[f"{lane}: health contract REVIEWED canary min_produced"] = (
        c.get("status") == "REVIEWED" and c.get("stage") == "canary"
        and (c.get("expected_output") or {}).get("rule") == "min_produced")
for lane in ("disk-hygiene", "tmp-hygiene"):
    hy = allow.get(lane) or {}
    checks[f"{lane}: --apply is never an allowlist argv"] = "--apply" not in json.dumps([hy.get(k) for k in ("command", "live_arg", "dry_run_arg")])
rules = j("config/disk_hygiene_rules.json")
checks["config/disk_hygiene_rules.json monitor.inodes + tmp rules"] = bool(rules.get("tmp")) and bool(rules["monitor"].get("inodes"))
checks["host routes host/disk_usage_{warn,critical,recovered}"] = {
    ("host", "disk_usage_warn"), ("host", "disk_usage_critical"), ("host", "disk_usage_recovered")} <= routes
checks["config/disk_hygiene_rules.json present"] = os.path.isfile(os.path.join(root, "config/disk_hygiene_rules.json"))
for name, good in checks.items():
    print(f"  {'ok ' if good else 'BAD'} {name}")
ok = all(checks.values())
print(f"  served {os.path.basename(root)}: " + ("DISK HYGIENE N8N PR SERVED" if ok else "PR NOT served (merge, then promote): stop here"))
sys.exit(0 if ok else 1)
EOF
}

restart_units(){ # $1 = expect | absent
  local u pid l
  for u in "${UNITS[@]}"; do
    "$SYSTEMCTL_BIN" --user restart "$u.service"; sleep "${RESTART_SETTLE_S:-2}"
    pid=$("$SYSTEMCTL_BIN" --user show -p MainPID --value "$u.service")
    [[ "$pid" =~ ^[0-9]+$ && "$pid" != 0 ]] || fail "$u has no MainPID after restart"
    for l in "${LANES[@]}"; do
      if tr '\0' '\n' < "$PROC_ROOT/$pid/environ" | grep -q -- "$l"; then
        [[ "$1" == expect ]] || fail "$u env still carries $l"
      else
        [[ "$1" == absent ]] || fail "$u env lacks $l after restart"
      fi
    done
    echo "  $u active, env $([[ "$1" == expect ]] && echo carries || echo no longer carries) ${LANES[*]}"
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
    served_state || true
    for l in "${LANES[@]}"; do
      if in_live_list "$l"; then echo "  live list HAS $l"; else echo "  live list lacks $l (relay step adds it)"; fi
    done
    for u in "${UNITS[@]}" "$GUARD_UNIT"; do echo "  $u: $("$SYSTEMCTL_BIN" --user is-active "$u.service" 2>/dev/null || true)"; done
    "$DOCKER_BIN" exec m8m-n8n-db psql -U n8n -d n8n -tA \
      -c "SELECT id||' active='||active::text||' updated='||\"updatedAt\"::text FROM workflow_entity WHERE id='$WID'" \
      2>/dev/null | sed 's/^/  n8n row: /' || true
    echo "  served disk_usage_monitor --dry-run (writes nothing):"
    (cd "$SERVED" && TRADEAI_STATE_ROOT="$STATE" "$PY" scripts/disk_usage_monitor.py --dry-run --state-root "$STATE" \
      | "$PY" -c 'import json,sys
d=json.loads(sys.stdin.read().split("DRY-RUN ",1)[1])["summary"]
for m in d["mounts"]:
    print("    %s %s%% band=%s previous=%s alert=%s" % (m["mount"], m.get("used_pct"), m.get("band"), m.get("previous_band"), m.get("alert")))') \
      || echo "    (monitor dry run failed)"
    echo "  served disk_hygiene --dry-run without sizes (writes nothing; dry-manifest measures):"
    (cd "$SERVED" && "$PY" scripts/disk_hygiene.py --dry-run --no-measure --state-root "$STATE" "${EXTRA_A[@]}" \
      | "$PY" -c 'import json,sys
t=json.loads(sys.stdin.read().split("DRY-RUN ",1)[1].split("\n",1)[0])["summary"]["totals"]
print("    candidates %s excluded %s by_kind %s" % (t["candidates"], t["excluded"], {k: v["count"] for k, v in t["by_kind"].items()}))') \
      || echo "    (hygiene dry run failed)" ;;
  dry-manifest)
    if [[ $APPLY == 1 ]]; then
      echo "  disk_hygiene --plan: manifest + receipt under $STATE (DELETES NOTHING)"
      (cd "$SERVED" && "$PY" scripts/disk_hygiene.py --plan --report --state-root "$STATE" "${EXTRA_A[@]}")
    else
      echo "  DRY RUN — disk_hygiene --dry-run --report (writes nothing)"
      (cd "$SERVED" && "$PY" scripts/disk_hygiene.py --dry-run --report --state-root "$STATE" "${EXTRA_A[@]}")
    fi ;;
  relay)
    need_grant
    served_state || fail "serve the disk-hygiene n8n PR first"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(live_lanes)
    [[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $LIVE_LANES_ENV"
    read -r -a CUR_A <<<"$CUR"
    ADD=()
    for l in "${LANES[@]}"; do in_live_list "$l" || ADD+=("$l"); done
    if [[ ${#ADD[@]} == 0 ]]; then echo "  live list already has ${LANES[*]}: nothing to do"; exit 0; fi
    echo "  adds: ${ADD[*]}"
    echo "  keeps: ${#CUR_A[@]} existing lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    write_live_list "$CUR ${ADD[*]}" disk-hygiene-n8n-live
    for l in "${LANES[@]}"; do in_live_list "$l" || fail "READ-BACK FAILED: $l not in $LIVE_LANES_ENV"; done
    for l in "${CUR_A[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    restart_units expect ;;
  publish)
    served_state || fail "serve the disk-hygiene n8n PR first"
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
    [[ "$act" == true ]] || fail "$WID is not active in n8n: the lanes cannot fire (activation is its own config-write act)"
    echo "  NO IMPORT NEEDED: this PR changes no workflow file. The lanes fire through the already-active $WID once"
    echo "  the registry rows (served) and the live list (relay) say live." ;;
  proof)
    [[ -z "$SINCE" || "$SINCE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T ]] || fail "--since must be ISO 8601 (UTC), e.g. 2026-10-18T16:00:00"
    set +e
    "$PY" - "$LEDGER" "$STATE" "$SINCE" "${LANES[@]}" <<'EOF'
import json, os, sqlite3, sys
ledger, state, since, lanes = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
verdict_ok = {}
for lane in lanes:
    q = "SELECT run_id, state, receipt_json, requested_at FROM runs WHERE lane_id=? AND mode='live' AND run_id LIKE ?"
    args = [lane, f"d:{lane}:live:%"]
    if since:
        q += " AND requested_at >= ?"; args.append(since)
    runs = c.execute(q + " ORDER BY requested_at", args).fetchall()
    good = False
    for run_id, st, rj, at in runs[-4:]:
        rec = json.loads(rj) if rj else {}
        ov = rec.get("output_verdict") or {}
        good = good or (st == "RUN_DONE" and ov.get("verdict") == "produced")
        print(f"  {lane} run {run_id}: {st} verdict={ov.get('verdict')} produced={ov.get('produced_count')}")
    bad = [r for r in runs if r[1] in ("RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED")]
    verdict_ok[lane] = good and not bad
    print(f"  {lane}: {'PASS' if verdict_ok[lane] else 'PENDING/FAIL'} (live runs {len(runs)}, failed {len(bad)})")
rt = os.path.join(state, "data", "runtime")
try:
    st = json.load(open(os.path.join(rt, "disk_usage_monitor_state.json")))
    for mount, row in (st.get("mounts") or {}).items():
        print(f"  monitor {mount}: band {row.get('band')} {row.get('last_pct')}% since {row.get('since')} alerted {row.get('alerted_at')}")
except (OSError, ValueError) as exc:
    print(f"  monitor state unreadable: {type(exc).__name__}")
intact = True
try:
    m = json.load(open(os.path.join(rt, "disk_hygiene", "disk_hygiene_manifest_latest.json")))
    t = m.get("totals") or {}
    print(f"  manifest {m.get('generated_at')}: candidates {t.get('candidates')} reclaimable {t.get('reclaimable_gb')} GB excluded {t.get('excluded')}")
    missing = [i["path"] for i in (m.get("items") or [])[:50] if not os.path.lexists(i["path"])]
    intact = not missing
    print(f"  plan deleted nothing: {'PASS' if intact else 'FAIL'} (first 50 items present; missing {missing[:3]})")
except (OSError, ValueError) as exc:
    print(f"  manifest unreadable: {type(exc).__name__} (the weekly lane fires Sun 04:00 ET; dry-manifest --apply writes one)")
sys.exit(0 if verdict_ok.get("disk-usage-monitor") and intact else 1)
EOF
    exit $? ;;
  backstop)
    PCT=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["monitor"]["host_backstop_pct"])' "$SERVED/config/disk_hygiene_rules.json")
    D="$HOME/.config/systemd/user/$GUARD_UNIT.service.d"
    cat <<EOF
  PRINT ONLY — this step changes nothing. Operator (service grant), to make the systemd guard a ${PCT}% host
  backstop (n8n's own Postgres fails when the disk is full, so the last line stays on the host, P1 direct):

    mkdir -p $D
    cat > $D/95-host-backstop.conf <<'UNIT'
    [Service]
    ExecStart=
    ExecStart=/bin/bash -lc 'PY=$REPO/.venv/bin/python; ROOT=$REPO; cd "\$ROOT"; exec "\$PY" scripts/disk_pressure_guard.py --used-pct $PCT'
    UNIT
    systemctl --user daemon-reload
    systemctl --user cat $GUARD_UNIT.service | tail -3      # read back: --used-pct $PCT
    systemctl --user start $GUARD_UNIT.service && tail -1 $REPO/logs/disk_pressure_guard_receipts.jsonl

  Rollback (archive, never delete):
    mv $D/95-host-backstop.conf $D/95-host-backstop.conf.disabled-\$(date +%Y%m%d) && systemctl --user daemon-reload
  Note: the guard shells disk_hygiene_enforcer.py --apply (release keep_n) when over its trigger; at ${PCT}% that
  reclaim fires later. tradeai-disk-hygiene-enforcer.timer (daily) and the weekly cleanup are unchanged.
EOF
    ;;
  hygiene-apply)
    MAN="$STATE/data/runtime/disk_hygiene/disk_hygiene_manifest_latest.json"
    [[ -f "$MAN" ]] || fail "no manifest at $MAN (dry-manifest --apply, or wait for the Sunday lane)"
    "$PY" - "$MAN" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1])); t = m["totals"]
print(f"  manifest {m['generated_at']}: {t['candidates']} candidates, {t['reclaimable_gb']} GB; by kind "
      + ", ".join(f"{k} {v['count']}" for k, v in sorted(t["by_kind"].items())))
EOF
    if [[ $APPLY == 0 ]]; then echo "  DRY RUN — nothing removed. Review the manifest, then: TRADEAI_DISK_HYGIENE_GRANT=<id> $0 hygiene-apply --apply"; exit 0; fi
    [[ -n "${TRADEAI_DISK_HYGIENE_GRANT:-}" ]] || fail "TRADEAI_DISK_HYGIENE_GRANT not set"
    [[ -z "${TRADEAI_RUN_ID:-}" ]] || fail "TRADEAI_RUN_ID is set: apply never runs under the n8n executor"
    (cd "$SERVED" && "$PY" scripts/disk_hygiene.py --apply --manifest "$MAN" --state-root "$STATE" "${EXTRA_A[@]}") ;;
  tmp-dry)
    echo "  DRY RUN — tmp_hygiene --dry-run --report (writes nothing, deletes nothing)"
    (cd "$SERVED" && "$PY" scripts/tmp_hygiene.py --dry-run --report --state-root "$STATE" "${EXTRA_A[@]}") ;;
  tmp-apply)
    MAN="$STATE/data/runtime/disk_hygiene/tmp_hygiene_manifest_latest.json"
    [[ -f "$MAN" ]] || fail "no /tmp manifest at $MAN (wait for the daily tmp-hygiene lane)"
    "$PY" - "$MAN" <<'EOF'
import json, sys
m = json.load(open(sys.argv[1])); t = m["totals"]
print(f"  /tmp manifest {m['generated_at']}: {t['candidates']} candidates, {t['reclaimable_files']} inodes, "
      f"{t['reclaimable_gb']} GB; by kind " + ", ".join(f"{k} {v['count']}" for k, v in sorted(t["by_kind"].items())))
EOF
    if [[ $APPLY == 0 ]]; then echo "  DRY RUN — nothing removed. Review the manifest, then: TRADEAI_DISK_HYGIENE_GRANT=<id> $0 tmp-apply --apply"; exit 0; fi
    [[ -n "${TRADEAI_DISK_HYGIENE_GRANT:-}" ]] || fail "TRADEAI_DISK_HYGIENE_GRANT not set"
    [[ -z "${TRADEAI_RUN_ID:-}" ]] || fail "TRADEAI_RUN_ID is set: apply never runs under the n8n executor"
    (cd "$SERVED" && "$PY" scripts/tmp_hygiene.py --apply --manifest "$MAN" --state-root "$STATE" "${EXTRA_A[@]}") ;;
  rollback)
    # R1 (this step, config-write + service grant): all three lanes leave the live list; the gateway then demotes every
    # dispatcher fire to dry_run (prints only). R2 (config): a PR that sets dispatch.mode dry_run / stage shadow and
    # live_arg null -> serve. NEVER deactivate tradeai-dispatcher: it fires every other dispatch-live lane. Receipts,
    # the monitor state and the manifests stay (rail 6); a queued band intent still reaches the operator.
    need_grant
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(live_lanes); read -r -a CUR_A <<<"$CUR"
    KEEP=(); DROP=()
    for l in "${CUR_A[@]}"; do
      if [[ " ${LANES[*]} " == *" $l "* ]]; then DROP+=("$l"); else KEEP+=("$l"); fi
    done
    if [[ ${#DROP[@]} == 0 ]]; then echo "  live list lacks ${LANES[*]}: nothing to roll back"; exit 0; fi
    echo "  removes: ${DROP[*]}; keeps ${#KEEP[@]} lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    write_live_list "${KEEP[*]}" disk-hygiene-n8n-rollback
    for l in "${LANES[@]}"; do if in_live_list "$l"; then fail "READ-BACK FAILED: $l still in $LIVE_LANES_ENV"; fi; done
    for l in "${KEEP[@]}"; do live_lanes | tr ' ' '\n' | grep -qx -- "$l" || fail "READ-BACK FAILED: lost $l"; done
    restart_units absent ;;
  *) fail "usage: $0 pre|dry-manifest|relay|publish|proof|backstop|hygiene-apply|tmp-dry|tmp-apply|rollback [--apply] [--since ISO]" ;;
esac
