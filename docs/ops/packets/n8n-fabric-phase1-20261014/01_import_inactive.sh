#!/usr/bin/env bash
# n8n fabric Phase 1 — import the four fabric workflows INACTIVE, then verify what n8n holds (trusted deployer).
#   bash 01_import_inactive.sh            # DRY RUN: runs 00_preflight.sh, prints the import it would do
#   bash 01_import_inactive.sh --apply    # needs TRADEAI_FABRIC_GRANT=<config-write grant id naming the four ids>
# `n8n import:workflow` without --activeState imports INACTIVE (n8n 2.43.0); each file also has "active": false.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SRC=$REPO/docs/implementation/n8n-maturity/workflows/fabric
RELAY=http://172.19.0.1:18092
IDS=(tradeai-fabric-run-lane tradeai-fabric-error tradeai-fabric-run-lane-probe tradeai-fabric-error-probe)
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
LIST=$(printf "'%s'," "${IDS[@]}"); LIST=${LIST%,}
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
fail(){ echo "REFUSED: $*"; exit 1; }

bash "$HERE/00_preflight.sh"
if [[ $APPLY == 0 ]]; then
  echo "DRY RUN OK — would run: docker exec m8m-n8n n8n import:workflow --separate --input=<stage> (INACTIVE),"
  echo "then n8n export:workflow --id=<id> for each and build-fabric --verify on the exports."
  exit 0
fi
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set (config-write grant naming the four ids)"
STAGE=/tmp/tradeai-fabric-$(date +%Y%m%dT%H%M%S)
mkdir -p "$STAGE/in" "$STAGE/out"
for id in "${IDS[@]}"; do cp "$SRC/$id.json" "$STAGE/in/"; done   # INDEX.json deliberately not staged
"$PY" "$REPO/scripts/check_n8n_import_ready.py" "$STAGE/in" --relay-url "$RELAY"
docker exec m8m-n8n mkdir -p "$STAGE/in" "$STAGE/out"
docker cp "$STAGE/in/." "m8m-n8n:$STAGE/in/"
docker exec m8m-n8n n8n import:workflow --separate --input="$STAGE/in/" 2>&1 | grep -v '^Postgres 16' || true

echo "== verify state (durable proof: workflow_entity rows)"
"${PSQL[@]}" -F' | ' -c "SELECT id, name, active, \"isArchived\", coalesce(\"activeVersionId\",'NULL') FROM workflow_entity WHERE id IN ($LIST) ORDER BY id"
N=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id IN ($LIST) AND NOT active AND \"activeVersionId\" IS NULL AND NOT \"isArchived\"")
[[ "$N" == "${#IDS[@]}" ]] || fail "post-import state wrong ($N of ${#IDS[@]} inactive) — run 09_rollback.sh (dry run first)"

echo "== trusted deployer: export what n8n now holds and verify graph + policy hash against the manifest"
for id in "${IDS[@]}"; do
  docker exec m8m-n8n n8n export:workflow --id="$id" --output="$STAGE/out/$id.json" 2>&1 | grep -v '^Postgres 16' || true
  docker cp "m8m-n8n:$STAGE/out/$id.json" "$STAGE/out/$id.json"
done
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --verify "$STAGE"/out/*.json \
  || fail "n8n holds a graph that is not the reviewed one — run 09_rollback.sh"
echo "IMPORT OK (grant $TRADEAI_FABRIC_GRANT). Nothing published. Stage kept at host+container:$STAGE (rail 6)."
