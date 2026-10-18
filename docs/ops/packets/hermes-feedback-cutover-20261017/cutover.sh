#!/usr/bin/env bash
# hermes-learning FEEDBACK cutover. Operator 2026-10-17 13:00 ET: "fix now move to n8n now"; decision D2 (packet
# hermes-learning-cutover-20261015 README) answered "queue reader first": the comms-intent consumer goes live on n8n
# BEFORE this step moves. Cutover standard 2026-10-14: fix + dry run + regression + >=1 live n8n run, no soak. Dry by
# default.
#
# Moves ONE learn step, outcome_feedback_agent (lane hermes-learning-outcome-feedback-agent), live on the fabric at the
# 10:50 ET learn slot with argv `--apply --notify queue`: each eligible closed-loop alert is QUEUED as a host comms
# intent (route research/hermes_closed_loop_alert); the lane calls no sender. The live n8n-comms-intent-consumer turns
# the intent into an incident for the incident notifier. Cron today sends the same alert directly (--notify chokepoint)
# from the 11:20 learn line, which already runs with PIPELINE_EFFECT_CLAIM=1: once n8n owns the effect key the cron
# step is skipped_effect. NO crontab change.
#
#   bash cutover.sh pre                    read-only: served PR state, consumer live?, owner, ownership, live list
#   bash cutover.sh relay   [--apply]      live list += the lane; restart relay AND gateway (service grant)
#   bash cutover.sh c3      [--apply]      owner cron -> n8n (refused 10:40-11:29 ET, before relay, or while the
#                                          comms-intent consumer is not live: alerts would queue and never be sent)
#   bash cutover.sh proof --date YYYYMMDD  read-only: n8n 10:50 live RUN_DONE + fx DONE scheduler n8n; cron 11:20
#                                          outcome_feedback_agent skipped_effect; today's queued intents consumed
#   bash cutover.sh rollback [--apply]     owner n8n -> cron (compare-and-swap): cron's 11:20 run sends again
#
# --apply needs TRADEAI_FABRIC_GRANT for the owner acts. This script never touches a broker, a secret value or an order.
# Test hooks (hermetic tests only): CRONTAB_BIN, FX_LEDGER, NOW_HM (HHMM ET), LIVE_LANES_ENV, SERVED, LEDGER.
set -euo pipefail
set -f
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
GRANT_PY=${GRANT_PY:-$(cd "$(dirname "$0")/../../../.." && pwd)/scripts/lib/fabric_grant.py}
SYSTEMCTL_BIN=${SYSTEMCTL_BIN:-systemctl}
PROC_ROOT=${PROC_ROOT:-/proc}
STATE=${STATE:-$HOME/trade-ai-releases/persistent-state}
LEDGER=${LEDGER:-$STATE/data/governance/n8n_coordination_ledger.sqlite}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
CRONTAB_BIN=${CRONTAB_BIN:-crontab}
LANE=hermes-learning-outcome-feedback-agent
CONSUMER=n8n-comms-intent-consumer
LEARN_LINE='PIPELINE_EFFECT_CLAIM=1 bash scripts/pipelines/run_hermes_pipeline.sh --stage learn --apply'
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
quiet_minute(){ local hm; hm=$(now_hm)  # n8n fires 10:50, cron 11:20: no owner act from 10:40 to 11:29 ET
  case "$hm" in 104*|105*|110*|111*|112*) fail "inside the learn window (10:40-11:29 ET): $hm";; esac; }
fx(){ "$PY" "$SERVED/scripts/lib/effect_claim.py" "${FXL[@]}" "$@"; }
owner_of(){ fx show --process "$LANE" \
  | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("none none" if o is None else "%s %s" % (o["owner"], o["epoch"]))'; }
listed(){ [[ -f "$LIVE_LANES_ENV" ]] && grep -q "^TRADEAI_N8N_RELAY_LIVE_LANES=.*\b$1\b" "$LIVE_LANES_ENV"; }

served_state(){ # exit 1 unless the feedback cutover PR is served
  SERVED="$SERVED" "$PY" - "$LANE" "$CONSUMER" <<'EOF'
import json, os, sys
root, lane, consumer = os.environ["SERVED"], sys.argv[1], sys.argv[2]
j = lambda rel: json.load(open(os.path.join(root, rel)))
allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}
reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}
eff = j("config/n8n_effect_keys.json")["lanes"].get(lane) or {}
step = j("config/n8n_fabric_processes.json")["processes"]["hermes-learning"]["steps"]["outcome_feedback_agent"]
want = ["--apply", "--notify", "queue"]
checks = {
    "registry stage canary": (reg.get(lane) or {}).get("scheduler", {}).get("stage") == "canary",
    "allowlist live_arg = --apply --notify queue": (allow.get(lane) or {}).get("live_arg") == step.get("cutover_live_arg") == want,
    "effect key cron_claim true (stage learn)": eff.get("cron_claim") is True and eff.get("stage") == "learn",
    "consumer scheduled (registry kind != none)": (reg.get(consumer) or {}).get("scheduler", {}).get("kind") not in (None, "none"),
    "consumer allowlist live_arg set": bool((allow.get(consumer) or {}).get("live_arg")),
}
for name, good in checks.items():
    print(f"  {'ok ' if good else 'BAD'} {name}")
ok = all(checks.values())
print(f"  served {os.path.basename(root)}: " + ("FEEDBACK CUTOVER PR SERVED" if ok else "PR (or consumer PR) NOT served: stop here"))
sys.exit(0 if ok else 1)
EOF
}

case "$STEP" in
  pre)
    echo "  now $(now_hm) ET (relay + c3 outside 10:40-11:29 ET)"
    served_state || true
    echo "  owner $LANE: $(owner_of)"
    fx ownership --process "$LANE" 2>/dev/null | sed 's/^/  ownership (decision ledger manifest p1 reason): /' || true
    echo "  crontab learn line:"; "$CRONTAB_BIN" -l | grep -n 'run_hermes_pipeline.sh --stage learn' | sed 's/^/    /'
    listed "$CONSUMER" && echo "  live list has $CONSUMER" || echo "  live list LACKS $CONSUMER (consumer PR first)"
    listed "$LANE" && echo "  live list has $LANE" || echo "  live list lacks $LANE" ;;
  relay)
    served_state || fail "serve the feedback cutover PR (and the consumer PR) first"
    [[ -f "$LIVE_LANES_ENV" ]] || fail "$LIVE_LANES_ENV missing"
    CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV")
    [[ -n "$CUR" ]] || fail "no TRADEAI_N8N_RELAY_LIVE_LANES= line in $LIVE_LANES_ENV"
    NEW=$(printf '%s\n' $CUR "$LANE" | awk 'NF && !seen[$0]++' | paste -sd' ')
    echo "  adds: $(comm -13 <(printf '%s\n' $CUR | sort -u) <(printf '%s\n' $NEW | sort -u) | paste -sd' ')"
    echo "  keeps: $(printf '%s\n' $CUR | grep -c .) existing lanes"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged, nothing restarted"; exit 0; }
    need_grant; quiet_minute
    cp -p "$LIVE_LANES_ENV" "$LIVE_LANES_ENV.bak-$(date -u +%Y%m%dT%H%M%SZ)-hermes-feedback"
    printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$LIVE_LANES_ENV.tmp" && chmod 600 "$LIVE_LANES_ENV.tmp" \
      && mv "$LIVE_LANES_ENV.tmp" "$LIVE_LANES_ENV"
    listed "$LANE" || fail "READ-BACK FAILED: $LANE not in $LIVE_LANES_ENV"
    for l in $CUR; do grep -qw -- "$l" "$LIVE_LANES_ENV" || fail "READ-BACK FAILED: lost $l"; done
    for u in tradeai-n8n-run-relay tradeai-n8n-coordination-gateway; do
      "$SYSTEMCTL_BIN" --user restart "$u.service"; sleep "${RESTART_SETTLE_S:-2}"
      pid=$("$SYSTEMCTL_BIN" --user show -p MainPID --value "$u.service")
      tr '\0' '\n' < "$PROC_ROOT/$pid/environ" | grep -q -- "$LANE" \
        && echo "  $u active, env carries $LANE" || fail "$u env lacks $LANE after restart"
    done ;;
  c3)
    served_state || fail "serve the feedback cutover PR (and the consumer PR) first"
    need_grant; quiet_minute
    "$CRONTAB_BIN" -l | grep -qF -- "$LEARN_LINE" || fail "the learn cron line does not claim effects (PIPELINE_EFFECT_CLAIM=1)"
    listed "$CONSUMER" || fail "$CONSUMER is not live: queued alerts would never reach the operator"
    listed "$LANE" || fail "relay not applied ($LANE not in the live list)"
    read -r cur ep <<<"$(owner_of)"
    [[ "$cur" == n8n ]] && { echo "  $LANE already n8n (epoch $ep)"; exit 0; }
    [[ "$cur" == cron ]] || fail "$LANE owner is '$cur' (expected cron)"
    ARGS=(set-owner --process "$LANE" --owner n8n --expect-epoch "$ep" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}"
          --note "hermes feedback cutover c3 (--apply --notify queue)")
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; exit 0; }
    fx "${ARGS[@]}" >/dev/null
    echo "  $LANE -> $(owner_of)"
    fx ownership --process "$LANE" 2>/dev/null | sed 's/^/  ownership now: /' || true ;;
  proof)
    [[ "$DATE" =~ ^[0-9]{8}$ ]] || fail "--date YYYYMMDD"
    set +e
    "$PY" - "$LEDGER" "$DATE" "$LANE" <<'EOF'
import sqlite3, sys
ledger, d, lane = sys.argv[1:4]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
runs = c.execute("SELECT run_id, state FROM runs WHERE lane_id=? AND mode='live' AND run_id LIKE ?",
                 (lane, f"p:{lane}:live:{d}T1050%")).fetchall()
fx = c.execute("SELECT state, scheduler FROM effect_claims WHERE effect_key=?", (f"fx:{lane}:{d}T1050:v1",)).fetchall()
iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
intents = c.execute("SELECT state, count(*) FROM comms_intents WHERE domain='research' AND kind='hermes_closed_loop_alert' "
                    "AND first_at LIKE ? GROUP BY state", (f"{iso}%",)).fetchall()
done = any(s == "RUN_DONE" for _, s in runs); fx_ok = any(s == "DONE" and sch == "n8n" for s, sch in fx)
stuck = sum(n for s, n in intents if s == "QUEUED")
print(f"  runs={runs} fx={fx} intents today={intents}")
ok = done and fx_ok and stuck == 0
print(f"  n8n half: {'PASS' if ok else 'FAIL'} (RUN_DONE={done} fx DONE n8n={fx_ok} intents still QUEUED={stuck})")
sys.exit(0 if ok else 1)
EOF
    rc=$?
    DD=$(date -d "$DATE" +%Y-%m-%d)
    J="$SERVED/logs/pipelines/hermes_learning/learn_steps.jsonl"
    L=$(grep -h "\"ts\": \"$DD" "$J" 2>/dev/null | grep '"dry_run": false' | grep '"id": "outcome_feedback_agent"' | tail -1 || true)
    if [[ -z "$L" ]]; then echo "  cron half: no live learn line for outcome_feedback_agent on $DD yet"; rc=1
    elif grep -q '"status": "skipped_effect"' <<<"$L"; then echo "  cron half: PASS (skipped_effect)"
    else echo "  cron half: FAIL ($L)"; rc=1; fi
    exit $rc ;;
  rollback)
    # R1: owner n8n -> cron; cron's 11:20 learn run sends the alert directly again. R2 (config-write): remove the lane
    # from the live list, restart relay + gateway. R3: revert the PR. Ledger rows stay (rail 6).
    need_grant
    read -r cur ep <<<"$(owner_of)"
    echo "  owner $LANE: $cur (epoch $ep)"
    [[ "$cur" == n8n ]] || { echo "  not n8n: nothing to roll back"; exit 0; }
    ARGS=(set-owner --process "$LANE" --owner cron --expect-epoch "$ep" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}"
          --note "hermes feedback cutover rollback R1")
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; exit 0; }
    fx "${ARGS[@]}" >/dev/null
    echo "  $LANE -> $(owner_of)" ;;
  *) fail "usage: $0 pre|relay|c3|proof|rollback [--apply] [--date YYYYMMDD]" ;;
esac
