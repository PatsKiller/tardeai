#!/usr/bin/env bash
# n8n fabric Phase 1 — import the four fabric workflows INACTIVE, then verify what n8n holds (trusted deployer).
#   bash 01_import_inactive.sh                      # DRY RUN: runs 00_preflight.sh, prints the import it would do
#   bash 01_import_inactive.sh --apply              # needs TRADEAI_FABRIC_GRANT=<config-write grant id naming the four ids>
#   bash 01_import_inactive.sh --reimport           # DRY RUN of a re-import over the INACTIVE fabric set (prints the plan)
#   bash 01_import_inactive.sh --reimport --apply   # re-import the regenerated files over them (same grant)
# `n8n import:workflow` without --activeState imports INACTIVE (n8n 2.43.0); each file also has "active": false.
# --reimport is allowed only when every n8n row matching a fabric id or name IS one of the four ids, inactive
# (active false), unpublished (activeVersionId NULL) and not archived (00_preflight.sh --reimport step 5, re-checked
# immediately before the import). The pre-image of each existing row is exported to the stage first (rail 6).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SRC=$REPO/docs/implementation/n8n-maturity/workflows/fabric
RELAY=http://172.19.0.1:18092
IDS=(tradeai-fabric-run-lane tradeai-fabric-error tradeai-fabric-run-lane-probe tradeai-fabric-error-probe)
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
# Every n8n CLI call starts its own task broker; the live instance already holds 5679 (operator run 2026-10-15).
N8N=(docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n)
LIST=$(printf "'%s'," "${IDS[@]}"); LIST=${LIST%,}
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
if [[ $APPLY == 0 ]]; then
  if [[ $REIMPORT == 1 ]]; then
    echo "DRY RUN OK (--reimport) — would run: n8n export:workflow --id=<id> of each existing row to <stage>/before"
    echo "(pre-image), re-check the step-5 state, n8n import:workflow --separate --input=<stage>/in over the plan above"
    echo "(INACTIVE), then n8n export:workflow --id=<id> for each and build-fabric --verify on the exports."
    echo "Graph hashes the exports must match (INDEX.json):"
    "$PY" -c 'import json,sys; [print("  ", r["id"], r["graph_sha256"]) for r in json.load(open(sys.argv[1]))["workflows"]]' "$SRC/INDEX.json"
  else
    echo "DRY RUN OK — would run: docker exec m8m-n8n n8n import:workflow --separate --input=<stage> (INACTIVE),"
    echo "then n8n export:workflow --id=<id> for each and build-fabric --verify on the exports."
  fi
  exit 0
fi
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set (config-write grant naming the four ids)"
STAGE=/tmp/tradeai-fabric-$(date +%Y%m%dT%H%M%S)
mkdir -p "$STAGE/in" "$STAGE/out" "$STAGE/before"
for id in "${IDS[@]}"; do cp "$SRC/$id.json" "$STAGE/in/"; done   # INDEX.json deliberately not staged
"$PY" "$REPO/scripts/check_n8n_import_ready.py" "$STAGE/in" --relay-url "$RELAY"
docker exec m8m-n8n mkdir -p "$STAGE/in" "$STAGE/out" "$STAGE/before"

if [[ $REIMPORT == 1 ]]; then
  echo "== pre-image: export each existing fabric row before it is replaced (kept, never deleted)"
  for id in "${IDS[@]}"; do
    [[ "$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$id'")" == "1" ]] || continue
    "${N8N[@]}" export:workflow --id="$id" --output="$STAGE/before/$id.json" 2>&1 | grep -v '^Postgres 16' || true
    docker cp "m8m-n8n:$STAGE/before/$id.json" "$STAGE/before/$id.json"
  done
  echo "== re-check immediately before the import (same rule as preflight step 5)"
  BAD=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE (id IN ($LIST) OR name IN ($LIST)) AND (id NOT IN ($LIST) OR active OR \"activeVersionId\" IS NOT NULL OR \"isArchived\")")
  [[ "$BAD" == "0" ]] || fail "state changed since preflight: $BAD fabric row(s) foreign, active, published or archived"
fi

docker cp "$STAGE/in/." "m8m-n8n:$STAGE/in/"
"${N8N[@]}" import:workflow --separate --input="$STAGE/in/" 2>&1 | grep -v '^Postgres 16' || true

echo "== verify state (durable proof: workflow_entity rows)"
"${PSQL[@]}" -F' | ' -c "SELECT id, name, active, \"isArchived\", coalesce(\"activeVersionId\",'NULL'), \"updatedAt\" FROM workflow_entity WHERE id IN ($LIST) ORDER BY id"
N=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id IN ($LIST) AND NOT active AND \"activeVersionId\" IS NULL AND NOT \"isArchived\"")
[[ "$N" == "${#IDS[@]}" ]] || fail "post-import state wrong ($N of ${#IDS[@]} inactive) — run 09_rollback.sh (dry run first)"

echo "== trusted deployer: export what n8n now holds and verify graph + policy hash against the manifest"
for id in "${IDS[@]}"; do
  "${N8N[@]}" export:workflow --id="$id" --output="$STAGE/out/$id.json" 2>&1 | grep -v '^Postgres 16' || true
  docker cp "m8m-n8n:$STAGE/out/$id.json" "$STAGE/out/$id.json"
done
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --verify "$STAGE"/out/*.json \
  || fail "n8n holds a graph that is not the reviewed one — run 09_rollback.sh"
WHAT=IMPORT; [[ $REIMPORT == 1 ]] && WHAT=REIMPORT
echo "$WHAT OK (grant $TRADEAI_FABRIC_GRANT). Nothing published. Stage kept at host+container:$STAGE (rail 6)."
