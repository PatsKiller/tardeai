#!/usr/bin/env bash
# hermes-learning cutover — ROLLBACK (target < 5 minutes, §23.6). Never deletes (rail 6). Dry by default.
#   bash 09_rollback.sh            # DRY RUN: current owners and every step below
#   bash 09_rollback.sh --apply    # owners n8n -> cron for the five learn lanes (compare-and-swap); needs TRADEAI_FABRIC_GRANT
# Order (each step reverses one cutover act; stop after the step that matches how far the cutover got):
#   R1 owners n8n -> cron (this script, --apply). From the next slot the cron runner claims and runs the five steps
#      again; an n8n live request is refused effect_fenced_owner (RUN_REFUSED, a status, no effect).
#   R2 unpublish the process if n8n must stop firing at all: bash ../n8n-hermes-learning-flow-20261015/09_rollback.sh --apply
#      (it also moves owners n8n -> cron, idempotent with R1).
#   R3 relay env (config-write grant): remove the five learn lanes from TRADEAI_N8N_RELAY_LIVE_LANES, restart the relay.
#   R4 config: revert the PR-2 merge (git revert -m 1 <merge sha> on a branch -> PR -> serve); spec mode dry_run,
#      live_arg null, stage shadow. PR-1 (cron_claim true) may stay: with owner cron it only records keys.
#   R5 crontab (cron grant): remove PIPELINE_EFFECT_CLAIM=1 from the learn line only if PR-1 is also reverted
#      (backup + read-back; the line text is otherwise unchanged; nothing was ever retired in this packet).
# Ledger rows (runs, run_outcomes, effect_claims, effect_owners, comms_intents) stay: they are the audit (rail 6).
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
LANES=(hermes-learning-outcome-grader hermes-learning-tag-engine hermes-learning-outcome-feedback-agent
       hermes-learning-outcome-learning hermes-learning-config-governor)
fail(){ echo "REFUSED: $*"; exit 1; }
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
for lane in "${LANES[@]}"; do
  read -r cur ep <<<"$("$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$lane" \
    | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("none none" if o is None else "%s %s" % (o["owner"], o["epoch"]))')"
  echo "  owner $lane: $cur (epoch $ep)"
  [[ "$cur" == "n8n" ]] || continue
  ARGS=(set-owner --process "$lane" --owner cron --expect-epoch "$ep" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}" --note "hermes-learning rollback R1")
  if [[ $APPLY == 0 ]]; then echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; continue; fi
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
  "$PY" "$SERVED/scripts/lib/effect_claim.py" "${ARGS[@]}"
done
echo "R1 $([[ $APPLY == 1 ]] && echo 'done' || echo 'dry run'). R2-R5: see the header (operator acts under their grants)."
