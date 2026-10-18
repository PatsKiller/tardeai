#!/usr/bin/env bash
# hermes-learning TUNE cutover: SAME-DAY sequence. Operator 2026-10-17 00:25 ET: "do a dry run now, it works no
# errors, make active now". Directive 2026-10-15: all families to n8n, with F41 retention approved for n8n. Cutover
# standard 2026-10-14: fix + dry run + regression + >=1 live n8n run with cron present, no soak. Dry by default.
#
# Moves the tune stage's ONE step, autonomous_self_tune (lane hermes-learning-autonomous-self-tune), live on the fabric
# at 17:00 ET. The lane runs the cron step's own argv, BOTH halves: auto-graft + archive-first self-purge. Once n8n
# owns the effect key, the cron step is skipped whole, so a learn-only lane would have silently stopped the purge.
# The cron tune line is NEVER commented here. It moves to 17:20 with PIPELINE_EFFECT_CLAIM=1 and is the "cron present"
# half: it claims fx:<lane>:<D>T1700:v1 (manifest minute) and is refused (skipped_effect) once n8n did it at 17:00.
#
#   bash cutover.sh pre                    read-only: served PR state, owner + handover manifest, crontab line,
#                                          n8n row, live list, yesterday's 17:00 fire
#   bash cutover.sh c1      [--apply]      owner row = cron for the lane if absent (operator did this 00:28 ET 10-17)
#   bash cutover.sh c2      [--apply]      CRONTAB (cron grant): tune line -> 20 17 + PIPELINE_EFFECT_CLAIM=1
#   bash cutover.sh relay   [--apply]      live list += the lane; restart relay AND gateway (service grant)
#   bash cutover.sh publish                read-only: confirms NO re-import is needed (graph unchanged by the PR)
#   bash cutover.sh c3      [--apply]      owner cron -> n8n (refused 16:50-17:29 ET and before c2 / relay)
#   bash cutover.sh proof --date YYYYMMDD  read-only: n8n 17:00 live RUN_DONE + fx DONE scheduler n8n + output verdict
#                                          produced|empty_allowed; cron 17:20 step skipped_effect
#   bash cutover.sh rollback [--apply]     owner n8n -> cron (compare-and-swap); see the ROLLBACK note at the bottom
#
# Order for today, ALL before 16:50 ET: (merge + serve the PR) -> pre -> c1 (done) -> c2 -> relay -> publish -> c3.
# The natural 17:00 ET fire is the live run. Manual live runs are refused by design (MANUAL_LIVE_REFUSED / EXPIRED).
# Cron's 17:20 run is the cron-present half; then run `proof --date <today>` after 17:25 ET.
# --apply needs TRADEAI_FABRIC_GRANT (the cron/config-write grant id) for the owner acts. c2 and relay also need the
# cron and config-write + service grants. This script never touches a broker, a secret value or an order.
# Test hooks (hermetic tests only): CRONTAB_BIN, FX_LEDGER (passed as --ledger to effect_claim.py), NOW_HM (HHMM ET).
set -euo pipefail
set -f
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
GRANT_PY=${GRANT_PY:-$(cd "$(dirname "$0")/../../../.." && pwd)/scripts/lib/fabric_grant.py}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER=${LEDGER:-$STATE/data/governance/n8n_coordination_ledger.sqlite}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
BACKUPS=${BACKUPS:-$HOME/.local/state/tradeai/backups}
CRONTAB_BIN=${CRONTAB_BIN:-crontab}
LANE=hermes-learning-autonomous-self-tune
WID=tradeai-fabric-hermes-learning
OLD_LINE='0 17 * * * cd $PROJ && bash scripts/pipelines/run_hermes_pipeline.sh --stage tune --apply'
NEW_LINE='20 17 * * * cd $PROJ && PIPELINE_EFFECT_CLAIM=1 bash scripts/pipelines/run_hermes_pipeline.sh --stage tune --apply'
FXL=(); [[ -n "${FX_LEDGER:-}" ]] && FXL=(--ledger "$FX_LEDGER")
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=${1:-}; shift || true
APPLY=0; DATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --date) DATE=${2:-}; shift 2 ;; *) fail "unknown arg $1" ;; esac
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
quiet_minute(){ local hm; hm=$(now_hm)  # n8n fires 17:00, cron 17:20: no owner act from 16:50 to 17:29 ET
  case "$hm" in 165*|170*|171*|172*) fail "inside the tune window (16:50-17:29 ET): $hm";; esac; }
fx(){ "$PY" "$SERVED/scripts/lib/effect_claim.py" "${FXL[@]}" "$@"; }
owner_of(){ fx show --process "$LANE" \
  | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("none none" if o is None else "%s %s" % (o["owner"], o["epoch"]))'; }
in_live_list(){ [[ -f "$LIVE_LANES_ENV" ]] && grep -q "^TRADEAI_N8N_RELAY_LIVE_LANES=.*\b${LANE}\b" "$LIVE_LANES_ENV"; }

served_state(){ # prints the served tune-cutover facts; exit 1 unless the PR is served
  SERVED="$SERVED" "$PY" - "$LANE" <<'EOF'
import json, os, sys
root, lane = os.environ["SERVED"], sys.argv[1]
j = lambda rel: json.load(open(os.path.join(root, rel)))
allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}.get(lane) or {}
reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}
eff = j("config/n8n_effect_keys.json")["lanes"].get(lane) or {}
proc = j("config/n8n_fabric_processes.json")["processes"]["hermes-learning"]
step = proc["steps"]["autonomous_self_tune"]
src = open(os.path.join(root, "scripts/hermes_autonomous_self_tune.py")).read()
checks = {
    "process mode live": proc.get("mode") == "live",
    "registry stage canary": (reg.get(lane) or {}).get("scheduler", {}).get("stage") == "canary",
    "allowlist command = cron argv (no --learn)": allow.get("command") == ["$PY", "scripts/hermes_autonomous_self_tune.py"],
    "allowlist live_arg = cutover_live_arg": allow.get("live_arg") == step.get("cutover_live_arg") == ["--apply"],
    "allowlist output_receipt v2": allow.get("output_receipt") == "v2",
    "effect key cron_claim true": eff.get("cron_claim") is True and eff.get("stage") == "tune",
    "registry tune runner at 20 17": reg["hermes-learning-pipeline-tune"]["scheduler"]["expression"] == "20 17 * * *",
    "script writes LaneRunReceipt@v2": "def lane_output" in src and "_write_receipt(True" in src,
}
for name, good in checks.items():
    print(f"  {'ok ' if good else 'BAD'} {name}")
ok = all(checks.values())
print(f"  served {os.path.basename(root)}: " + ("TUNE CUTOVER PR SERVED" if ok else "PR NOT served (merge, then release): stop here"))
sys.exit(0 if ok else 1)
EOF
}

case "$STEP" in
  pre)
    echo "  now $(now_hm) ET (everything through c3 must be done before 16:50 ET)"
    served_state || true
    echo "  owner $LANE: $(owner_of)"
    fx ownership --process "$LANE" 2>/dev/null | sed 's/^/  ownership (decision ledger manifest p1 reason): /' || true
    echo "  crontab tune line:"; "$CRONTAB_BIN" -l | grep -n 'run_hermes_pipeline.sh --stage tune' | sed 's/^/    /'
    docker exec m8m-n8n-db psql -U n8n -d n8n -tA \
      -c "SELECT id||' active='||active::text||' updated='||\"updatedAt\"::text FROM workflow_entity WHERE id='$WID'" 2>/dev/null \
      | sed 's/^/  n8n row: /' || true
    docker exec m8m-n8n-db psql -U n8n -d n8n -tA -c "SELECT id||' '||status||' '||mode||' '||\"startedAt\"::text \
      FROM execution_entity WHERE \"workflowId\"='$WID' ORDER BY id DESC LIMIT 3" 2>/dev/null \
      | sed 's/^/  last executions: /' || true
    echo "  (yesterday's 17:00 tune fire ended error: refused_policy relay_live_not_enabled: the lane is not in the live"
    echo "   list yet; the relay step below is what makes 17:00 run)"
    in_live_list && echo "  live list has $LANE" || echo "  live list lacks $LANE" ;;
  c1)
    need_grant
    read -r cur ep <<<"$(owner_of)"
    case "$cur" in
      cron|n8n) echo "  $LANE owner already $cur (epoch $ep): nothing to do"; exit 0 ;;
      none) ;;
      *) fail "unexpected owner '$cur'" ;;
    esac
    ARGS=(set-owner --process "$LANE" --owner cron --by "operator:${TRADEAI_FABRIC_GRANT:-dry}" --note "hermes tune cutover c1")
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; exit 0; }
    fx "${ARGS[@]}" >/dev/null
    echo "  $LANE -> $(owner_of)" ;;
  c2)
    served_state || fail "serve the tune cutover PR first (the registry expects the tune line at 20 17)"
    mkdir -p "$BACKUPS"; W=$(mktemp -d)
    "$CRONTAB_BIN" -l > "$W/live"
    n_old=$(grep -cF -- "$OLD_LINE" "$W/live" || true); n_new=$(grep -cF -- "$NEW_LINE" "$W/live" || true)
    [[ "$n_new" == 1 && "$n_old" == 0 ]] && { echo "  already applied: $(grep -nF -- "$NEW_LINE" "$W/live")"; exit 0; }
    [[ "$n_old" == 1 && "$n_new" == 0 ]] || fail "expected exactly one tune line starting '$OLD_LINE' (found $n_old; new $n_new)"
    OLD_LINE="$OLD_LINE" NEW_LINE="$NEW_LINE" "$PY" - "$W/live" "$W/cand" <<'EOF'
import os, sys
old, new = os.environ["OLD_LINE"], os.environ["NEW_LINE"]
src = open(sys.argv[1], newline="").read()
lines = src.split("\n")
hits = [i for i, l in enumerate(lines) if l.startswith(old)]
assert len(hits) == 1, hits
lines[hits[0]] = new + lines[hits[0]][len(old):]
open(sys.argv[2], "w", newline="").write("\n".join(lines))
EOF
    diff "$W/live" "$W/cand" | sed 's/^/    /' || true
    [[ "$(diff "$W/live" "$W/cand" | grep -c '^[<>]')" == 2 ]] || fail "diff is not exactly one line"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — crontab unchanged"; exit 0; }
    B="$BACKUPS/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-hermes-tune-c2.txt"; cp -p "$W/live" "$B"
    "$CRONTAB_BIN" - < "$W/cand"
    "$CRONTAB_BIN" -l | cmp - "$W/cand" && echo "  installed byte-exact; backup $B" \
      || fail "READ-BACK MISMATCH — restore: $CRONTAB_BIN $B" ;;
  relay)
    served_state || fail "serve the tune cutover PR first"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV")
    [[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $LIVE_LANES_ENV"
    NEW=$(printf '%s\n' $CUR "$LANE" | awk 'NF && !seen[$0]++' | paste -sd' ')
    echo "  adds: $(comm -13 <(printf '%s\n' $CUR | sort -u) <(printf '%s\n' $NEW | sort -u) | paste -sd' ')"
    echo "  keeps: $(printf '%s\n' $CUR | grep -c .) existing lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    cp -p "$LIVE_LANES_ENV" "$LIVE_LANES_ENV.bak-$(date -u +%Y%m%dT%H%M%SZ)-hermes-tune"
    printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$LIVE_LANES_ENV.tmp" && chmod 600 "$LIVE_LANES_ENV.tmp" \
      && mv "$LIVE_LANES_ENV.tmp" "$LIVE_LANES_ENV"
    in_live_list || fail "READ-BACK FAILED: $LANE not in $LIVE_LANES_ENV"
    for l in $CUR; do grep -qw -- "$l" "$LIVE_LANES_ENV" || fail "READ-BACK FAILED: lost $l"; done
    # the gateway reads the same file (its due-computation demotes a live lane missing from its env): restart BOTH
    for u in tradeai-n8n-run-relay tradeai-n8n-coordination-gateway; do
      systemctl --user restart "$u.service"; sleep 2
      pid=$(systemctl --user show -p MainPID --value "$u.service")
      tr '\0' '\n' < "/proc/$pid/environ" | grep -q -- "$LANE" \
        && echo "  $u active, env carries $LANE" || fail "$u env lacks $LANE after restart"
    done ;;
  publish)
    served_state || fail "serve the tune cutover PR first"
    SERVED="$SERVED" "$PY" - "$WID" <<'EOF' || fail "served fabric workflow differs from the published PR-2 graph: re-import with $HERE/../n8n-hermes-learning-flow-20261015/03_publish_shadow.sh"
import hashlib, json, os, sys
root, wid = os.environ["SERVED"], sys.argv[1]
d = os.path.join(root, "docs/implementation/n8n-maturity/workflows/fabric")
row = next(w for w in json.load(open(os.path.join(d, "INDEX.json")))["workflows"] if w["id"] == wid)
sha = hashlib.sha256(open(os.path.join(d, row["file"]), "rb").read()).hexdigest()
# graph published 2026-10-16 17:19Z (PR-2 + manual-slots PR); this PR leaves the file byte-identical
want = "f1d0984c64b06191020008af6d09f8b26a9c5a0ba5789f8e97ddb0e45215ebe4"
print(f"  served graph_sha256 {row['graph_sha256']} file sha256 {sha} (index {row['sha256']})")
sys.exit(0 if row["graph_sha256"] == want and sha == row["sha256"] else 1)
EOF
    docker exec m8m-n8n-db psql -U n8n -d n8n -tA \
      -c "SELECT 'n8n row active='||active::text FROM workflow_entity WHERE id='$WID'" 2>/dev/null | sed 's/^/  /' || true
    echo "  NO RE-IMPORT NEEDED: the tune step's schedule (17:00) and the process mode (live) are already published;"
    echo "  the step goes live through the registry stage (served), the live list (relay) and the owner row (c3)." ;;
  c3)
    served_state || fail "serve the tune cutover PR first"
    need_grant; quiet_minute
    "$CRONTAB_BIN" -l | grep -qF -- "$NEW_LINE" || fail "c2 not applied (the tune line must claim effects before n8n owns them)"
    in_live_list || fail "relay not applied ($LANE not in the live list): n8n would be refused relay_live_not_enabled and cron skipped — no tune today"
    read -r cur ep <<<"$(owner_of)"
    [[ "$cur" == n8n ]] && { echo "  $LANE already n8n (epoch $ep)"; exit 0; }
    [[ "$cur" == cron ]] || fail "$LANE owner is '$cur': run c1 first"
    ARGS=(set-owner --process "$LANE" --owner n8n --expect-epoch "$ep" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}"
          --note "hermes tune cutover c3 (autonomous_self_tune, both halves)")
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; exit 0; }
    fx "${ARGS[@]}" >/dev/null  # set-owner writes the handover manifest too (fail-closed ownership, PR #1845)
    echo "  $LANE -> $(owner_of)"
    fx ownership --process "$LANE" 2>/dev/null | sed 's/^/  ownership now: /' || true ;;
  proof)
    [[ "$DATE" =~ ^[0-9]{8}$ ]] || fail "--date YYYYMMDD"
    set +e
    "$PY" - "$LEDGER" "$STATE" "$DATE" "$LANE" <<'EOF'
import json, os, sqlite3, sys
ledger, state, d, lane = sys.argv[1:5]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
runs = c.execute("SELECT run_id, state, receipt_json FROM runs WHERE lane_id=? AND mode='live' AND run_id LIKE ?",
                 (lane, f"p:{lane}:live:{d}T1700%")).fetchall()
fx = c.execute("SELECT state, scheduler, run_id FROM effect_claims WHERE effect_key=?",
               (f"fx:{lane}:{d}T1700:v1",)).fetchall()
verdicts = []
for run_id, st, rj in runs:
    rec = json.loads(rj) if rj else None
    if rec is None:
        p = os.path.join(state, "data", "runtime", "n8n_runs", f"{run_id}.json")
        rec = json.load(open(p)) if os.path.isfile(p) else {}
    ov = rec.get("output_verdict") or {}
    verdicts.append(ov.get("verdict"))
    print(f"  run {run_id}: {st} verdict={ov.get('verdict')} produced_count={ov.get('produced_count')} "
          f"empty_reason={ov.get('empty_reason')} skipped={ov.get('skipped_reasons')}")
print(f"  fx {lane}:{d}T1700: {fx}")
done = any(st == "RUN_DONE" for _, st, _ in runs)
fx_ok = any(s == "DONE" and sch == "n8n" for s, sch, _ in fx)
useful = any(v in ("produced", "empty_allowed") for v in verdicts)
ok = done and fx_ok and useful
print(f"  n8n half: {'PASS' if ok else 'FAIL'} (RUN_DONE={done} fx DONE n8n={fx_ok} output verdict produced|empty_allowed={useful})")
sys.exit(0 if ok else 1)
EOF
    rc=$?
    echo "  cron half (17:20 ET run, same date): autonomous_self_tune must be skipped_effect (rc 75):"
    DD=$(date -d "$DATE" +%Y-%m-%d)
    J="$SERVED/logs/pipelines/hermes_learning/tune_steps.jsonl"
    LINES=$(grep -h "\"ts\": \"$DD" "$J" 2>/dev/null | grep '"dry_run": false' || true)
    if [[ -z "$LINES" ]]; then echo "    (no tune_steps.jsonl live line for $DD yet)"; rc=1
    else
      printf '%s\n' "$LINES" | "$PY" -c 'import json,sys
for l in sys.stdin:
    d=json.loads(l); print("    %s %-22s %s rc=%s fx=%s" % (d["ts"], d["id"], d["status"], d.get("rc"), d.get("effect_key")))'
      printf '%s\n' "$LINES" | tail -1 | grep -q '"status": "skipped_effect"' && echo "  cron half: PASS" \
        || { echo "  cron half: FAIL (last live tune line is not skipped_effect)"; rc=1; }
    fi
    exit $rc ;;
  rollback)
    # R1 (this step): owner n8n -> cron. From the next slot the 17:20 cron run claims and runs the step again; an n8n
    # live request is refused effect_fenced_owner. R2 (relay env, config-write grant): remove the lane from the live
    # list, restart relay + gateway. R3 (config): revert the PR on a branch -> PR -> serve. R4 (cron grant): restore
    # the crontab backup from c2 (0 17, no PIPELINE_EFFECT_CLAIM). Ledger rows stay (rail 6).
    need_grant
    read -r cur ep <<<"$(owner_of)"
    echo "  owner $LANE: $cur (epoch $ep)"
    [[ "$cur" == n8n ]] || { echo "  not n8n: nothing to roll back"; exit 0; }
    ARGS=(set-owner --process "$LANE" --owner cron --expect-epoch "$ep" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}"
          --note "hermes tune cutover rollback R1")
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; exit 0; }
    fx "${ARGS[@]}" >/dev/null
    echo "  $LANE -> $(owner_of)" ;;
  *) fail "usage: $0 pre|c1|c2|relay|publish|c3|proof|rollback [--apply] [--date YYYYMMDD]" ;;
esac
