#!/usr/bin/env bash
# n8n fabric process hermes-learning — STEP 2: one CLI dry-run proof of the INACTIVE process (publishes nothing).
#   bash 02_verify.sh            # DRY RUN: prints what it would execute
#   bash 02_verify.sh --apply    # needs TRADEAI_FABRIC_GRANT
# `n8n execute --id` starts from the Manual Trigger ("Manual run"): Plan manual -> stage 'all' -> learn then tune, mode
# dry_run, slot = the current America/New_York minute (never a scheduled slot). Expected (config/n8n_fabric_processes.json):
# three Run Lane calls (outcome_grader -> outcome_learning -> config_governor), four steps recorded `blocked`, overall
# `partial`, CLI exit 0. The CLI prints the last node's output (FabricProcessResult@v1: every step's run_id + status).
# Manual executions are not saved (saveManualExecutions false), so the durable proof is the ledger (04_evidence.py).
# Pick a minute away from 10:50 and 17:00 ET (the stage runner's slots) so the single executor worker is idle.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
WF=tradeai-fabric-hermes-learning
N8N=(docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n)
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
fail(){ echo "REFUSED: $*"; exit 1; }
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
SINCE=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
HM=$(TZ=America/New_York date +%H%M)
echo "V1: ${N8N[*]} execute --id=$WF   (start node: Manual run; dry_run; slot $(TZ=America/New_York date +%Y%m%dT%H%M))"
[[ $APPLY == 1 ]] || { echo "DRY RUN — nothing executed"; exit 0; }
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
case "$HM" in 104*|105*|110*|111*|112*|113*|114*|115*|165*|170*|171*) fail "too close to a stage slot ($HM ET)";; esac
A=$("${PSQL[@]}" -c "SELECT active::text||'|'||coalesce(\"activeVersionId\",'NULL') FROM workflow_entity WHERE id='$WF'")
[[ "$A" == "false|NULL" ]] || fail "$WF must be imported and INACTIVE for this proof (got '$A')"
RC=0
LOG=/tmp/tradeai-fabric-hl-verify-$$.log
"${N8N[@]}" execute --id="$WF" > "$LOG" 2>&1 || RC=$?
grep -v '^Postgres 16' "$LOG" | tail -80 || true
echo "n8n execute exit code: $RC (full log $LOG)"
echo "== n8n executions since $SINCE (deletedAt IS NULL; CLI runs may not be stored)"
"${PSQL[@]}" -F' | ' -c "SELECT \"workflowId\", status, mode, \"startedAt\" FROM execution_entity WHERE \"deletedAt\" IS NULL AND \"startedAt\" >= '$SINCE' AND \"workflowId\" LIKE 'tradeai-fabric-%' ORDER BY \"startedAt\"" || true
"$PY" "$HERE/04_evidence.py" --since "$SINCE" --manual
