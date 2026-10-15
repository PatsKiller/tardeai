#!/usr/bin/env bash
# n8n fabric process hermes-learning — STEP 1: import the process workflow INACTIVE, then verify what n8n holds.
#   bash 01_import_inactive.sh                     # DRY RUN: runs 00_preflight.sh, prints the import it would do
#   bash 01_import_inactive.sh --apply             # needs TRADEAI_FABRIC_GRANT (grant naming tradeai-fabric-hermes-learning)
#   bash 01_import_inactive.sh --reimport [--apply]  # over the INACTIVE process row (pre-image exported first)
# `n8n import:workflow` without --activeState imports INACTIVE (n8n 2.43); the file also has "active": false.
# Every n8n CLI call runs with N8N_RUNNERS_BROKER_PORT=5690 (the live instance holds 5679; Build 1 finding F1).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SRC=$REPO/docs/implementation/n8n-maturity/workflows/fabric
WF=tradeai-fabric-hermes-learning
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
N8N=(docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n)
fail(){ echo "REFUSED: $*"; exit 1; }
APPLY=0; REIMPORT=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --reimport) REIMPORT=1 ;;
    *) fail "usage: $0 [--reimport] [--apply]" ;;
  esac
done
PRE=(); [[ $REIMPORT == 1 ]] && PRE=(--reimport)

bash "$HERE/00_preflight.sh" "${PRE[@]}"
GRAPH=$("$PY" -c 'import json,sys; print(next(r["graph_sha256"] for r in json.load(open(sys.argv[1]))["workflows"] if r["id"]==sys.argv[2]))' "$SRC/INDEX.json" "$WF")
if [[ $APPLY == 0 ]]; then
  echo "DRY RUN OK — would run: n8n import:workflow --input=<stage>/in/$WF.json (INACTIVE), then"
  echo "n8n export:workflow --id=$WF and build-fabric --verify on the export (graph hash must be $GRAPH)."
  exit 0
fi
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set (grant naming $WF; reason 'PR #N sha <sha>')"
STAGE=/tmp/tradeai-fabric-hl-$(date +%Y%m%dT%H%M%S)
mkdir -p "$STAGE/in" "$STAGE/out" "$STAGE/before"
cp "$SRC/$WF.json" "$STAGE/in/"
docker exec m8m-n8n mkdir -p "$STAGE/in" "$STAGE/out" "$STAGE/before"
if [[ $REIMPORT == 1 && "$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF'")" == "1" ]]; then
  "${N8N[@]}" export:workflow --id="$WF" --output="$STAGE/before/$WF.json" 2>&1 | grep -v '^Postgres 16' || true
  docker cp "m8m-n8n:$STAGE/before/$WF.json" "$STAGE/before/$WF.json"
  BAD=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF' AND (active OR \"activeVersionId\" IS NOT NULL OR \"isArchived\")")
  [[ "$BAD" == "0" ]] || fail "state changed since preflight (active, published or archived)"
fi
docker cp "$STAGE/in/." "m8m-n8n:$STAGE/in/"
"${N8N[@]}" import:workflow --separate --input="$STAGE/in/" 2>&1 | grep -v '^Postgres 16' || true

echo "== verify state (durable proof: workflow_entity row)"
"${PSQL[@]}" -F' | ' -c "SELECT id, name, active, \"isArchived\", coalesce(\"activeVersionId\",'NULL'), \"updatedAt\" FROM workflow_entity WHERE id='$WF'"
N=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF' AND NOT active AND \"activeVersionId\" IS NULL AND NOT \"isArchived\"")
[[ "$N" == "1" ]] || fail "post-import state wrong — run 09_rollback.sh (dry run first)"

echo "== trusted deployer: export what n8n holds and verify graph + policy hash against INDEX.json"
"${N8N[@]}" export:workflow --id="$WF" --output="$STAGE/out/$WF.json" 2>&1 | grep -v '^Postgres 16' || true
docker cp "m8m-n8n:$STAGE/out/$WF.json" "$STAGE/out/$WF.json"
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --verify "$STAGE/out/$WF.json" \
  || fail "n8n holds a graph that is not the reviewed one — run 09_rollback.sh"
echo "IMPORT OK (grant $TRADEAI_FABRIC_GRANT). INACTIVE, nothing published. Stage kept at $STAGE (rail 6)."
