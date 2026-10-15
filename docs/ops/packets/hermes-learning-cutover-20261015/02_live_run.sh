#!/usr/bin/env bash
# hermes-learning cutover — STEP 2: the fenced single-owner switch and the live n8n run with cron still present
# (§23.21 ">=1 live n8n run", §23.23 migration rule (4)). LEARN stage only. Dry by default.
#   bash 02_live_run.sh --step c1 [--apply]   owner rows = cron for the five learn lanes (effect_claim.py set-owner)
#   bash 02_live_run.sh --step c2             PRINTS the crontab edit (operator, cron grant): PIPELINE_EFFECT_CLAIM=1
#   bash 02_live_run.sh --step relay          PRINTS the relay live-lanes edit (operator, config-write grant)
#   bash 02_live_run.sh --step c3 [--apply]   THE recorded act: owners cron -> n8n (compare-and-swap on the epoch)
#   bash 02_live_run.sh --step c4 --date YYYYMMDD   read-only evidence of the live slot (03_parity.py --mode live)
# --apply needs TRADEAI_FABRIC_GRANT (the cron/config-write grant id). This script writes ONLY effect_owners rows, through
# the served scripts/lib/effect_claim.py. It never edits the crontab, a unit, the relay env or a config file.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
LANES=(hermes-learning-outcome-grader hermes-learning-tag-engine hermes-learning-outcome-feedback-agent
       hermes-learning-outcome-learning hermes-learning-config-governor)
fail(){ echo "REFUSED: $*"; exit 1; }
STEP=""; APPLY=0; DATE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --step) STEP=${2:-}; shift 2 ;;
    --apply) APPLY=1; shift ;;
    --date) DATE=${2:-}; shift 2 ;;
    *) fail "usage: $0 --step c1|c2|relay|c3|c4 [--apply] [--date YYYYMMDD]" ;;
  esac
done

owner_of(){ "$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$1" \
  | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("none none" if o is None else "%s %s" % (o["owner"], o["epoch"]))'; }

set_owner(){ # $1 target owner
  local target=$1
  for lane in "${LANES[@]}"; do
    read -r cur ep <<<"$(owner_of "$lane")"
    if [[ "$cur" == "$target" ]]; then echo "  $lane already $target (epoch $ep)"; continue; fi
    if [[ "$target" == "n8n" && "$cur" != "cron" ]]; then fail "$lane owner is '$cur': C1 first"; fi
    ARGS=(set-owner --process "$lane" --owner "$target" --by "operator:${TRADEAI_FABRIC_GRANT:-dry}" --note "hermes-learning cutover $STEP")
    [[ "$ep" != "none" ]] && ARGS+=(--expect-epoch "$ep")
    if [[ $APPLY == 0 ]]; then echo "  DRY RUN — would run: effect_claim.py ${ARGS[*]}"; continue; fi
    [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
    "$PY" "$SERVED/scripts/lib/effect_claim.py" "${ARGS[@]}"
  done
}

case "$STEP" in
  c1)
    "$PY" "$HERE/00_gate_check.py" --phase builds || fail "builds not served"
    set_owner cron ;;
  c2)
    "$PY" "$HERE/00_gate_check.py" --phase claim || echo "  (gate above must PASS before the edit: PR-1 served + C1 done)"
    cat <<'TXT'
  OPERATOR (cron grant; backup + read-back):
    crontab -l > ~/crontab.backup.$(date +%Y%m%dT%H%M%S)
    crontab -e     # on the learn stage line ONLY, insert PIPELINE_EFFECT_CLAIM=1 before `bash`:
      50 10 * * * cd $PROJ && PIPELINE_EFFECT_CLAIM=1 bash scripts/pipelines/run_hermes_pipeline.sh --stage learn --apply >> logs/pipelines/hermes_cron.log 2>&1  # TRADEAI_LANE hermes-learning-pipeline-learn (parallel dry-run)
    crontab -l | grep -n 'run_hermes_pipeline.sh --stage learn'      # read back: exactly one line, with the prefix
  Verify the next natural 10:50 run (owner still cron): learn_steps.jsonl lines carry an fx key and status ok, and
  effect_claims holds fx:<lane>:<YYYYMMDD>T1050:v1 DONE scheduler cron for the five lanes.
  Decision D1 (README): optionally move this line to 20 11 * * * (and its registry match in the same PR) so the
  cron-only retention step runs after n8n's grader. The effect slot stays <date>T1050 either way (manifest minute).
TXT
    ;;
  relay)
    cat <<TXT
  OPERATOR (config-write grant): add the five learn lanes to TRADEAI_N8N_RELAY_LIVE_LANES in ~/.config/tradeai/n8n-relay.env
  (space-separated; keep every existing lane), then: systemctl --user restart tradeai-n8n-run-relay.service
    ${LANES[*]}
  Read back: grep -c hermes-learning ~/.config/tradeai/n8n-relay.env   (expect the line to list all five)
TXT
    ;;
  c3)
    "$PY" "$HERE/00_gate_check.py" --phase live || fail "phase live gates not met (00_gate_check.py --phase live)"
    HM=$(TZ=America/New_York date +%H%M)
    case "$HM" in 104*|105*|11*) fail "do the owner switch at a quiet minute, not inside the 10:40-11:59 ET learn window ($HM)";; esac
    set_owner n8n
    echo "  From here the cron runner's claims for these five steps are refused (skipped_effect) and the next scheduled"
    echo "  10:50 n8n learn fire is the live run with cron still present (C4: --step c4 --date <that date>)." ;;
  c4)
    [[ -n "$DATE" ]] || fail "--date YYYYMMDD"
    "$PY" "$HERE/03_parity.py" --date "$DATE" --mode live ;;
  *) fail "usage: $0 --step c1|c2|relay|c3|c4 [--apply] [--date YYYYMMDD]" ;;
esac
