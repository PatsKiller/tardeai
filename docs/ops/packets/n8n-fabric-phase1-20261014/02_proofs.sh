#!/usr/bin/env bash
# n8n fabric Phase 1 — the two live dry-run proofs (README "DRY-RUN PROOF PLAN").
#   bash 02_proofs.sh --probe [--apply]        P1: CLI run of the inactive Run Lane probe (dry_run lane; publishes nothing)
#   bash 02_proofs.sh --error-proof [--apply]  P2: publish the error probe for ONE scheduled fire, then unpublish
# --apply needs TRADEAI_FABRIC_GRANT. Without --apply each prints what it would do and exits.
# Every n8n CLI call here (execute, publish:workflow, unpublish:workflow) runs with N8N_RUNNERS_BROKER_PORT=5690: the CLI
# process starts its own task broker and the live instance already holds 5679 ("n8n Task Broker's port 5679 is
# already in use", operator run 2026-10-15). The probe starts from its Manual Trigger (the CLI refuses a workflow
# whose only start node is a Schedule Trigger: "Missing node to start execution").
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
BROKER_PORT=5690
N8N=(docker exec -e N8N_RUNNERS_BROKER_PORT=$BROKER_PORT m8m-n8n n8n)
MODE=${1:-}; APPLY=0; [[ "${2:-}" == "--apply" ]] && APPLY=1
fail(){ echo "REFUSED: $*"; exit 1; }
[[ "$MODE" == "--probe" || "$MODE" == "--error-proof" ]] || fail "usage: $0 --probe|--error-proof [--apply]"
SINCE=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)

if [[ "$MODE" == "--probe" ]]; then
  echo "P1: ${N8N[*]} execute --id=tradeai-fabric-run-lane-probe   (start node: Manual run)"
  echo "    -> Run Lane: POST /run (crontab-snapshot-for-health-agent, dry_run) -> poll GET /run_outcome -> result"
  [[ $APPLY == 1 ]] || { echo "DRY RUN — nothing executed"; exit 0; }
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
  RC=0
  "${N8N[@]}" execute --id=tradeai-fabric-run-lane-probe > "/tmp/tradeai-fabric-probe-$$.log" 2>&1 || RC=$?
  grep -v '^Postgres 16' "/tmp/tradeai-fabric-probe-$$.log" | tail -40 || true
  echo "n8n execute exit code: $RC (evidence below either way; full log /tmp/tradeai-fabric-probe-$$.log)"
else
  echo "P2: at hh:07 or hh:37 — publish tradeai-fabric-error-probe, restart n8n, wait for ONE fire (<= 75 s),"
  echo "    unpublish, restart. Its failure must start tradeai-fabric-error (automatic failure, addendum item 9)."
  [[ $APPLY == 1 ]] || { echo "DRY RUN — nothing published"; exit 0; }
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
  M=$((10#$(date +%M) % 30)); [[ $M -ge 5 && $M -le 10 ]] || fail "not a quiet minute (want hh:05-hh:10 or hh:35-hh:40)"
  echo "active before: $("${PSQL[@]}" -c 'SELECT count(*) FROM workflow_entity WHERE active')"
  "${N8N[@]}" publish:workflow --id=tradeai-fabric-error-probe 2>&1 | grep -v '^Postgres 16' || true
  docker restart m8m-n8n >/dev/null
  for _ in $(seq 1 30); do
    sleep 5
    N=$("${PSQL[@]}" -c "SELECT count(*) FROM execution_entity WHERE \"workflowId\"='tradeai-fabric-error-probe' AND \"deletedAt\" IS NULL AND \"startedAt\" >= '$SINCE'")
    [[ "$N" -ge 1 ]] && break
  done
  "${N8N[@]}" unpublish:workflow --id=tradeai-fabric-error-probe 2>&1 | grep -v '^Postgres 16' || true
  docker restart m8m-n8n >/dev/null
  echo "active after: $("${PSQL[@]}" -c 'SELECT count(*) FROM workflow_entity WHERE active') (must equal before)"
  sleep 20
fi

echo "== n8n executions since $SINCE (deletedAt IS NULL)"
"${PSQL[@]}" -F' | ' -c "SELECT \"workflowId\", status, mode, \"startedAt\" FROM execution_entity WHERE \"deletedAt\" IS NULL AND \"startedAt\" >= '$SINCE' AND \"workflowId\" LIKE 'tradeai-fabric-%' ORDER BY \"startedAt\""
"${PSQL[@]}" -F' | ' -c "SELECT e.\"workflowId\", m.key, m.value FROM execution_metadata m JOIN execution_entity e ON e.id = m.\"executionId\" WHERE e.\"startedAt\" >= '$SINCE' AND e.\"workflowId\" LIKE 'tradeai-fabric-%'" || true
"$PY" "$HERE/03_evidence.py" --since "$SINCE"
