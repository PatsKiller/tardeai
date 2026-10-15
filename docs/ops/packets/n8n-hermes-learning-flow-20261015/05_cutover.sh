#!/usr/bin/env bash
# n8n fabric process hermes-learning — STEP 5: cutover (§23.21 standard + §23.23 rule (4) fenced single-owner switch).
#   bash 05_cutover.sh                          # READ-ONLY: gate check (prints what is met and what is not)
#   bash 05_cutover.sh --owner cron [--apply]   # create/confirm the effect-key owner rows = cron (step C1)
#   bash 05_cutover.sh --owner n8n  [--apply]   # THE recorded act: move every runnable step's owner cron -> n8n (C3)
# --apply needs TRADEAI_FABRIC_GRANT. This script writes ONLY effect_owners rows through scripts/lib/effect_claim.py
# set-owner (compare-and-swap on the epoch). It never edits the crontab: the crontab edits below are the operator's,
# under a cron grant, with a backup (crontab -l > backup) and read-back (crontab -l | grep).
#
# GATES (all must hold before --owner n8n; README "CUTOVER"):
#   G1 shadow: 5 consecutive learn slots print "verdict": "PARITY" (04_evidence.py --date D --stage learn).
#   G2 zero BLOCKED steps in config/n8n_fabric_processes.json, OR the operator's recorded choice of the partial path.
#   G3 merged + served: gateway validates p:<lane>:<mode>:<slot> keys against the process spec (today a live p: run is
#      refused effect:effect_slot_unknown by the executor, fail closed); spec mode "live"; allowlist live_arg
#      ["--apply"]; registry stage cutover; cron_claim true for the runnable lanes; relay live-lanes env lists them.
#   G4 the run_with_deepseek_offpeak.sh time gate is reproduced on the n8n path (its schedule is inside the wrapper's
#      window today, but the wrapper is also a PEAK_SKIP gate the executor does not apply).
# SEQUENCE (each step is one operator act; 09_rollback.sh reverses each):
#   C1 05_cutover.sh --owner cron --apply            owner rows exist (epoch 1); nothing changes behaviour yet.
#   C2 crontab: prefix both stage lines with PIPELINE_EFFECT_CLAIM=1 (cron grant). The runner now claims each
#      cron_claim step as owner cron: same behaviour, keys recorded (verify one natural run: effect_key on receipts).
#   C3 05_cutover.sh --owner n8n --apply             at a quiet minute: from here the cron runner's claims are refused
#      (skipped_effect, nothing runs) and the n8n live run claims the same key. Cron is still present = the §23.21
#      "one live n8n run with cron still present under a shared lock": fire it (scheduled slot, or manual).
#   C4 evidence: 04_evidence.py for that slot shows n8n RUN_DONE live with effect DONE (scheduler n8n) and the cron
#      step skipped_effect; the step lock was shared (allowlist lock == the step command's lock).
#   C5 crontab (cron grant): comment the stage line(s) `# RETIRED <date> n8n-process hermes-learning <line>`, never
#      delete; only when that stage has no BLOCKED step left (otherwise the runner keeps running the blocked steps).
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
fail(){ echo "REFUSED: $*"; exit 1; }
OWNER=""; APPLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER=${2:-}; shift 2 ;;
    --apply) APPLY=1; shift ;;
    *) fail "usage: $0 [--owner cron|n8n] [--apply]" ;;
  esac
done
mapfile -t LANES < <("$PY" -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["lanes"]))' "$SERVED/config/n8n_effect_keys.json")
echo "effect-key lanes in the served release: ${LANES[*]:-none}"

echo "== gate check (read-only)"
"$PY" - "$SERVED" <<'PY' || true
import json, sys
root = sys.argv[1]
spec = json.load(open(f"{root}/config/n8n_fabric_processes.json"))["processes"]["hermes-learning"]
allow = {e["lane_id"]: e for e in json.load(open(f"{root}/config/n8n_run_allowlist.json"))["lanes"]}
reg = {r["lane_id"]: r for r in json.load(open(f"{root}/config/lane_registry.json"))["lanes"]}
eff = json.load(open(f"{root}/config/n8n_effect_keys.json"))["lanes"]
blocked = [s for s, v in spec["steps"].items() if v["blocked"]]
print(f"  G2 blocked steps: {blocked or 'none'}  -> {'NOT MET' if blocked else 'met'}")
print(f"  G3 spec mode: {spec['mode']}  -> {'met' if spec['mode'] == 'live' else 'NOT MET'}")
for sid, v in spec["steps"].items():
    if v["blocked"]:
        continue
    lane = v["lane_id"]
    e, r, x = allow.get(lane, {}), reg.get(lane, {}), eff.get(lane, {})
    ok = e.get("live_arg") == ["--apply"] and r.get("scheduler", {}).get("stage") == "cutover" and x.get("cron_claim") is True
    print(f"  G3 {lane}: live_arg={e.get('live_arg')} stage={r.get('scheduler', {}).get('stage')} "
          f"cron_claim={x.get('cron_claim')}  -> {'met' if ok else 'NOT MET'}")
print("  G1 (5x PARITY) and G4 (off-peak gate) and the gateway p: key validation: operator evidence, not checked here")
PY
for lane in "${LANES[@]}"; do
  "$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$lane" | sed "s/^/  owner $lane: /"
done
[[ -n "$OWNER" ]] || { echo "READ-ONLY gate check done (no --owner given)"; exit 0; }
[[ "$OWNER" == "cron" || "$OWNER" == "n8n" ]] || fail "--owner must be cron or n8n"
[[ ${#LANES[@]} -gt 0 && -n "${LANES[0]}" ]] || fail "no effect-key lanes served"
for lane in "${LANES[@]}"; do
  CUR=$("$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$lane" | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("" if o is None else "%s %s" % (o["owner"], o["epoch"]))')
  read -r COWN CEP <<<"${CUR:-none none}"
  if [[ "$COWN" == "$OWNER" ]]; then echo "  $lane already owned by $OWNER (epoch $CEP)"; continue; fi
  [[ "$OWNER" == "n8n" && "$COWN" != "cron" ]] && fail "$lane: owner is '$COWN'; C1 (--owner cron) and C2 come first"
  ARGS=(set-owner --process "$lane" --owner "$OWNER" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}" --note "hermes-learning cutover")
  [[ "$CEP" != "none" ]] && ARGS+=(--expect-epoch "$CEP")
  if [[ $APPLY == 0 ]]; then echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; continue; fi
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
  "$PY" "$SERVED/scripts/lib/effect_claim.py" "${ARGS[@]}"
done
echo "OWNER STEP DONE ($OWNER; apply=$APPLY)"
