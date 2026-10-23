#!/usr/bin/env bash
# hermes-learning cutover — SAME-MORNING sequence (operator-approved 2026-10-16: "approved ... Hermes PR-2"; n8n cutover
# standard 2026-10-14: fix + dry run + regression + >=1 live n8n run with cron present, no soak). Dry by default.
#
# Moves FOUR learn steps live on the fabric (tests/support/hermes_learning_cutover.py LIVE): outcome_grader, tag_engine,
# outcome_learning, config_governor. HELD on cron: score_history_retention (destructive retention, operator decision)
# and the tune stage (manifest split first). outcome_feedback_agent was HELD here (its `--notify queue` argv tripped the
# allowlist sender token gate) until the 2026-10-17 feedback cutover aligned that gate; it is in LIVE now and its own
# same-day packet is docs/ops/packets/hermes-feedback-cutover-20261017/cutover.sh (relay / c3 here are idempotent with
# it: the live list dedups and c3 skips a lane already owned by n8n). HELD is empty and kept for the pre/c3 reports.
# The learn cron line is NEVER commented here: it keeps running retention.
#
#   bash 11_cutover_today.sh pre                    read-only: served PR-1/PR-2 state, owners, crontab line, n8n row
#   bash 11_cutover_today.sh import  [--apply]      flow 01_import_inactive.sh, then flow 02_verify.sh (CLI dry-run proof)
#   bash 11_cutover_today.sh c1      [--apply]      owner rows = cron for all five learn lanes (02_live_run.sh --step c1)
#   bash 11_cutover_today.sh c2      [--apply]      CRONTAB (cron grant): learn line -> 20 11, PIPELINE_EFFECT_CLAIM=1
#   bash 11_cutover_today.sh relay   [--apply]      live list += the four LIVE lanes; restart relay AND gateway
#   bash 11_cutover_today.sh publish [--apply]      flow 03_publish_shadow.sh (arms 10:50 learn / 17:00 tune triggers)
#   bash 11_cutover_today.sh c3      [--apply]      owners cron -> n8n for the four LIVE lanes only (quiet minute)
#   bash 11_cutover_today.sh manual  [--apply]      FALLBACK ONLY (one-day manual-slots PR served): one manual LIVE run
#                                                   when today's 10:50 effect never happened on either side (see below)
#   bash 11_cutover_today.sh proof --date YYYYMMDD  read-only: n8n 10:50 live RUN_DONE + fx DONE scheduler n8n, and the
#                                                   11:20 cron run skipped_effect for the LIVE lanes, ok for retention
# Order for one morning: pre -> import -> c1 -> c2 -> relay -> publish -> c3, all done before 10:40 ET; the natural
# 10:50 ET fire is the live run (manual live runs are refused by design: MANUAL_LIVE_REFUSED); cron's 11:20 run is the
# "cron present" half; then `proof`. --apply needs TRADEAI_FABRIC_GRANT (the cron/config-write grant id) for owner and
# n8n acts; c2 and relay also need the cron / config-write + service grants. Never touches a broker, secret or order.
set -euo pipefail
set -f
HERE=$(cd "$(dirname "$0")" && pwd)
FLOW="$HERE/../n8n-hermes-learning-flow-20261015"
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
LIVE_LANES_ENV=${LIVE_LANES_ENV:-$HOME/.config/tradeai/n8n-live-lanes.env}
BACKUPS=${BACKUPS:-$HOME/.local/state/tradeai/backups}
LIVE=(hermes-learning-outcome-grader hermes-learning-tag-engine hermes-learning-outcome-learning
      hermes-learning-config-governor hermes-learning-outcome-feedback-agent)
HELD=()  # empty since the 2026-10-17 feedback cutover (tests/support/hermes_learning_cutover.py HELD)
OLD_LINE='50 10 * * * cd $PROJ && bash scripts/pipelines/run_hermes_pipeline.sh --stage learn --apply'
NEW_LINE='20 11 * * * cd $PROJ && PIPELINE_EFFECT_CLAIM=1 bash scripts/pipelines/run_hermes_pipeline.sh --stage learn --apply'
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=${1:-}; shift || true
APPLY=0; DATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in --apply) APPLY=1; shift ;; --date) DATE=${2:-}; shift 2 ;; *) fail "unknown arg $1" ;; esac
done
AF=(); [[ $APPLY == 1 ]] && AF=(--apply)
need_grant(){ [[ $APPLY == 0 || -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"; }
quiet_minute(){ local hm; hm=$(TZ=America/New_York date +%H%M)
  case "$hm" in 104*|105*|11*|165*|170*|171*) fail "not inside a stage window (10:40-11:59 / 16:50-17:19 ET): $hm";; esac; }
owner_of(){ "$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$1" \
  | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("none none" if o is None else "%s %s" % (o["owner"], o["epoch"]))'; }

served_state(){ # prints the served PR-1/PR-2 facts; exit 1 if PR-2 is not served
  SERVED="$SERVED" "$PY" - "${LIVE[@]}" -- "${HELD[@]}" <<'EOF'
import json, os, sys
root = os.environ["SERVED"]
args = sys.argv[1:]; i = args.index("--"); live, held = args[:i], args[i + 1:]
j = lambda rel: json.load(open(os.path.join(root, rel)))
proc = j("config/n8n_fabric_processes.json")["processes"]
proc = proc["hermes-learning"] if isinstance(proc, dict) else next(p for p in proc if p.get("id") == "hermes-learning")
allow = {e["lane_id"]: e for e in j("config/n8n_run_allowlist.json")["lanes"]}
reg = {r["lane_id"]: r for r in j("config/lane_registry.json")["lanes"]}
eff = j("config/n8n_effect_keys.json")["lanes"]
steps = {s["lane_id"]: s for s in proc["steps"].values() if s.get("lane_id")}
ok = proc.get("mode") == "live"
print(f"  served {os.path.basename(root)}: spec mode={proc.get('mode')} live_manual_slots={proc.get('live_manual_slots')}")
for lane in live + held:
    st = (reg.get(lane) or {}).get("scheduler", {}).get("stage")
    la = (allow.get(lane) or {}).get("live_arg")
    cc = (eff.get(lane) or {}).get("cron_claim")
    want_stage, want_la = ("canary", steps[lane].get("cutover_live_arg")) if lane in live else ("shadow", None)
    good = st == want_stage and la == want_la and cc is True
    ok &= good
    print(f"  {'ok ' if good else 'BAD'} {lane}: stage={st} live_arg={la} cron_claim={cc}")
print("  PR-1 + PR-2 SERVED" if ok else "  PR-1/PR-2 NOT served (merge, then release) — stop here")
sys.exit(0 if ok else 1)
EOF
}

case "$STEP" in
  pre)
    served_state || true
    for lane in "${LIVE[@]}" "${HELD[@]}"; do echo "  owner $lane: $(owner_of "$lane")"; done
    echo "  crontab learn line:"; crontab -l | grep -n 'run_hermes_pipeline.sh --stage learn' | sed 's/^/    /'
    docker exec m8m-n8n-db psql -U n8n -d n8n -tA \
      -c "SELECT id||' active='||active::text FROM workflow_entity WHERE id='tradeai-fabric-hermes-learning'" 2>/dev/null \
      | sed 's/^/  n8n row: /' || true
    grep -c . "$LIVE_LANES_ENV" >/dev/null 2>&1 && for l in "${LIVE[@]}"; do
      grep -qw -- "$l" "$LIVE_LANES_ENV" && echo "  live list has $l" || echo "  live list lacks $l"; done
    "$PY" "$HERE/00_gate_check.py" --phase builds || true ;;
  import)
    served_state || fail "serve PR-1 + PR-2 first"
    need_grant
    bash "$FLOW/01_import_inactive.sh" "${AF[@]}"
    bash "$FLOW/02_verify.sh" "${AF[@]}" ;;
  c1)
    need_grant
    bash "$HERE/02_live_run.sh" --step c1 "${AF[@]}" ;;
  c2)
    served_state || fail "serve PR-1 + PR-2 first (the registry expects the learn line at 20 11)"
    mkdir -p "$BACKUPS"; W=$(mktemp -d)
    crontab -l > "$W/live"
    n_old=$(grep -cF -- "$OLD_LINE" "$W/live" || true); n_new=$(grep -cF -- "$NEW_LINE" "$W/live" || true)
    [[ "$n_new" == 1 && "$n_old" == 0 ]] && { echo "  already applied: $(grep -nF -- "$NEW_LINE" "$W/live")"; exit 0; }
    [[ "$n_old" == 1 ]] || fail "expected exactly one learn line starting '$OLD_LINE' (found $n_old)"
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
    B="$BACKUPS/crontab-$(date -u +%Y%m%dT%H%M%SZ)-pre-hermes-learning-c2.txt"; cp -p "$W/live" "$B"
    crontab - < "$W/cand"
    crontab -l | cmp - "$W/cand" && echo "  installed byte-exact; backup $B" || fail "READ-BACK MISMATCH — restore: crontab $B" ;;
  relay)
    served_state || fail "serve PR-1 + PR-2 first"
    CUR=$(sed -n 's/^TRADEAI_N8N_RELAY_LIVE_LANES=//p' "$LIVE_LANES_ENV")
    NEW=$(printf '%s\n' $CUR "${LIVE[@]}" | awk 'NF && !seen[$0]++' | paste -sd' ')
    echo "  adds: $(comm -13 <(printf '%s\n' $CUR | sort -u) <(printf '%s\n' $NEW | sort -u) | paste -sd' ')"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — live list unchanged"; exit 0; }
    cp -p "$LIVE_LANES_ENV" "$LIVE_LANES_ENV.bak-$(date -u +%Y%m%dT%H%M%SZ)-hermes-learning"
    printf 'TRADEAI_N8N_RELAY_LIVE_LANES=%s\n' "$NEW" > "$LIVE_LANES_ENV.tmp" && chmod 600 "$LIVE_LANES_ENV.tmp" \
      && mv "$LIVE_LANES_ENV.tmp" "$LIVE_LANES_ENV"
    for l in "${LIVE[@]}"; do grep -qw -- "$l" "$LIVE_LANES_ENV" || fail "READ-BACK FAILED: $l"; done
    # the gateway reads the same file (its due-computation demotes a live lane missing from its env): restart BOTH
    for u in tradeai-n8n-run-relay tradeai-n8n-coordination-gateway; do
      systemctl --user restart "$u.service"; sleep 2
      pid=$(systemctl --user show -p MainPID --value "$u.service")
      tr '\0' '\n' < "/proc/$pid/environ" | grep -q "hermes-learning-config-governor" \
        && echo "  $u active, env carries the four lanes" || fail "$u env lacks the lanes after restart"
    done ;;
  publish)
    served_state || fail "serve PR-1 + PR-2 first"
    need_grant; quiet_minute
    bash "$FLOW/03_publish_shadow.sh" "${AF[@]}"
    echo "  NEXT (Agent A, same day): registry PR flipping the six step rows NEVER_SCHEDULED -> ACTIVE + the active"
    echo "  workflow snapshot (check_lane_registry rule), as the flow packet's 03 header says." ;;
  c3)
    served_state || fail "serve PR-1 + PR-2 first"
    need_grant; quiet_minute
    # captured, not piped: `crontab -l | grep -q` under pipefail is a false failure (SIGPIPE, 2026-10-22)
    CT="$(crontab -l)" || fail "crontab -l failed"
    grep -qF -- "$NEW_LINE" <<<"$CT" || fail "c2 not applied (learn line must claim effects before n8n owns them)"
    for lane in "${LIVE[@]}"; do
      read -r cur ep <<<"$(owner_of "$lane")"
      [[ "$cur" == n8n ]] && { echo "  $lane already n8n (epoch $ep)"; continue; }
      [[ "$cur" == cron ]] || fail "$lane owner is '$cur': run c1 first"
      ARGS=(set-owner --process "$lane" --owner n8n --expect-epoch "$ep" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}"
            --note "hermes-learning cutover c3 (LIVE learn lanes incl. feedback agent since 2026-10-17)")
      if [[ $APPLY == 0 ]]; then echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; continue; fi
      "$PY" "$SERVED/scripts/lib/effect_claim.py" "${ARGS[@]}" >/dev/null
      echo "  $lane -> $(owner_of "$lane")"
    done
    for lane in "${HELD[@]}"; do echo "  held $lane stays $(owner_of "$lane")"; done ;;
  manual)
    # Fallback when the morning missed 10:40 (e.g. c3 landed between 10:50 and 11:20: n8n's 10:50 fire was fenced and
    # cron's 11:20 run skipped the four). A manual minute's effect key differs from the stage slot's, so it is allowed
    # ONLY when today's fx:<lane>:<D>T1050:v1 is not DONE for any LIVE lane AND cron recorded no ok step for them today
    # AND it is after 12:00 ET (no scheduled fire still to come) — otherwise it would double today's effect.
    served_state || fail "serve PR-1 + PR-2 first"
    need_grant
    HM=$(TZ=America/New_York date +%H%M); (( 10#$HM > 1200 && 10#$HM < 2330 )) || fail "manual proof only 12:00-23:30 ET ($HM)"
    SERVED="$SERVED" "$PY" - <<'EOF2' || fail "one-day manual-slots flag not served or expired"
import json, os
from datetime import datetime, timezone
p = json.load(open(os.path.join(os.environ["SERVED"], "config/n8n_fabric_processes.json")))["processes"]
p = p["hermes-learning"] if isinstance(p, dict) else next(x for x in p if x.get("id") == "hermes-learning")
until = p.get("live_manual_slots_until")
ok = p.get("live_manual_slots") is True and until and datetime.now(timezone.utc) < datetime.fromisoformat(until)
print(f"  served live_manual_slots={p.get('live_manual_slots')} until={until}")
raise SystemExit(0 if ok else 1)
EOF2
    for lane in "${LIVE[@]}"; do read -r cur _ <<<"$(owner_of "$lane")"; [[ "$cur" == n8n ]] || fail "$lane owner $cur: c3 first"; done
    D=$(TZ=America/New_York date +%Y%m%d); DD=$(TZ=America/New_York date +%Y-%m-%d)
    LEDGER=${LEDGER:-$HOME/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite}
    "$PY" - "$LEDGER" "$D" "${LIVE[@]}" <<'EOF2' || fail "today's effect already happened for a LIVE lane: a manual run would double it"
import sqlite3, sys
ledger, d, lanes = sys.argv[1], sys.argv[2], sys.argv[3:]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
done = [l for l in lanes if c.execute("SELECT 1 FROM effect_claims WHERE process=? AND slot LIKE ? AND state='DONE'",
                                      (l, f"{d}T%")).fetchone()]
print(f"  effect DONE today: {done or 'none'}")
raise SystemExit(1 if done else 0)
EOF2
    J="$SERVED/logs/pipelines/hermes_learning/learn_steps.jsonl"
    if grep -h "\"ts\": \"$DD" "$J" 2>/dev/null | grep -E '"id": "(outcome_grader|tag_engine|outcome_learning|config_governor|outcome_feedback_agent)"' \
         | grep -q '"status": "ok"'; then fail "cron ran a LIVE step ok today: a manual run would double it"; fi
    N8N=(docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n)
    echo "  PLAN: ${N8N[*]} execute --id=tradeai-fabric-hermes-learning  (Manual run -> stage all, mode live, manual minute)"
    [[ $APPLY == 1 ]] || { echo "  DRY RUN — nothing executed"; exit 0; }
    "${N8N[@]}" execute --id=tradeai-fabric-hermes-learning 2>&1 | grep -v '^Postgres 16' | tail -20
    echo "  then: bash $0 proof --date $D  (the n8n half reads the manual slot as well)" ;;
  proof)
    [[ -n "$DATE" ]] || fail "--date YYYYMMDD"
    LEDGER=${LEDGER:-$HOME/trade-ai-releases/persistent-state/data/governance/n8n_coordination_ledger.sqlite}
    set +e
    "$PY" - "$LEDGER" "$DATE" "${LIVE[@]}" <<'EOF'
import sqlite3, sys
ledger, d, lanes = sys.argv[1], sys.argv[2], sys.argv[3:]
c = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
ok = True
for lane in lanes:
    runs = c.execute("SELECT run_id, state FROM runs WHERE lane_id=? AND mode='live' AND run_id LIKE ?",
                     (lane, f"%:live:{d}T%")).fetchall()  # the 10:50 stage slot, or the one manual fallback minute
    fx = c.execute("SELECT state, scheduler FROM effect_claims WHERE process=? AND slot LIKE ?", (lane, f"{d}T%")).fetchall()
    good = any(s == "RUN_DONE" for _, s in runs) and any(st == "DONE" and sch == "n8n" for st, sch in fx)
    ok &= good
    print(f"  {'PROOF' if good else 'MISSING'} {lane}: runs={runs} fx={fx}")
print("  n8n half:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
EOF
    rc=$?
    echo "  cron half (11:20 run, same date): the LIVE lanes must be skipped_effect; retention ok:"
    # same file 03_parity.py reads; one JSON line per step (PipelineStepReceipt@v1)
    grep -h "\"ts\": \"$(date -d "$DATE" +%Y-%m-%d)T1[45]:" "$SERVED/logs/pipelines/hermes_learning/learn_steps.jsonl" 2>/dev/null \
      | "$PY" -c 'import json,sys
for l in sys.stdin:
    d=json.loads(l); print("    %s %-24s %s rc=%s dry_run=%s" % (d["ts"], d["id"], d["status"], d.get("rc"), d.get("dry_run")))' \
      || echo "    (no learn_steps.jsonl lines for that date yet)"
    exit $rc ;;
  *) fail "usage: $0 pre|import|c1|c2|relay|publish|c3|manual|proof [--apply] [--date YYYYMMDD]" ;;
esac
