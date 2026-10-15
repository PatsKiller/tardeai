#!/usr/bin/env bash
# n8n fabric Phase 1 — read-only preflight (no n8n write, no ledger write, no unit touched).
#   bash 00_preflight.sh              # first import: the four ids must be ABSENT from n8n
#   bash 00_preflight.sh --reimport   # re-import: every fabric row present must be one of the four ids, INACTIVE
#                                     # (active false, activeVersionId NULL = no published version), not archived
# Modelled on ~/n8n-maturity-verification/packets/w0-import-six/import-six.sh steps 0-6.
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SRC=$REPO/docs/implementation/n8n-maturity/workflows/fabric
RELAY=http://172.19.0.1:18092
RELAY_ROOT=${RELAY_ROOT:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
IDS=(tradeai-fabric-run-lane tradeai-fabric-error tradeai-fabric-run-lane-probe tradeai-fabric-error-probe)
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
LIST=$(printf "'%s'," "${IDS[@]}"); LIST=${LIST%,}
fail(){ echo "REFUSED: $*"; exit 1; }
REIMPORT=0
case "${1:-}" in
  "") ;;
  --reimport) REIMPORT=1 ;;
  *) fail "usage: $0 [--reimport]" ;;
esac

echo "== 0. source tree $(git -C "$REPO" rev-parse HEAD); uncommitted under fabric/: $(git -C "$REPO" status --porcelain -- "$SRC" | wc -l)"
[[ -z "$(git -C "$REPO" status --porcelain -- "$SRC")" ]] || fail "fabric dir has uncommitted changes"

echo "== 1. generator: committed fabric set == fresh render; generic set unchanged"
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --check || fail "fabric set stale"
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-generic --check || fail "generic set stale"

echo "== 2. trusted-deployer verify of the files against the manifest (graph + policy hash, node allowlist)"
files=(); for id in "${IDS[@]}"; do files+=("$SRC/$id.json"); done
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --verify "${files[@]}" || fail "verify"

echo "== 3. repo import gate"
"$PY" "$REPO/scripts/check_n8n_import_ready.py" "$SRC" --relay-url "$RELAY" || fail "import gate"

echo "== 4. relay contract vs the SERVED relay ($RELAY_ROOT): static ROUTES + scratch-relay probe"
SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/fabric-relay-contract.XXXXXX")
TRADE_AI_CI=1 "$PY" "$REPO/scripts/check_n8n_relay_contract.py" --workflows "$SRC" --relay-root "$RELAY_ROOT" \
  --scratch "$SCRATCH" --no-concurrency \
  || fail "relay contract: is the release that adds GET /run_outcome and POST /intent served? (scratch kept at $SCRATCH)"
"$PY" "$RELAY_ROOT/scripts/n8n_run_relay.py" --routes

if [[ $REIMPORT == 0 ]]; then
  echo "== 5. ids absent from n8n (incl. archived)"
  DB=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id IN ($LIST) OR name IN ($LIST)")
  echo "workflow_entity rows with these ids/names: $DB"
  [[ "$DB" == "0" ]] || fail "id/name collision: an import would overwrite; stop and report (re-import of the INACTIVE fabric set: --reimport)"
else
  echo "== 5. --reimport: every row matching a fabric id OR name is a fabric id, INACTIVE, unpublished, not archived"
  "${PSQL[@]}" -F' | ' -c "SELECT id, name, active, \"isArchived\", coalesce(\"activeVersionId\",'NULL') FROM workflow_entity WHERE id IN ($LIST) OR name IN ($LIST) ORDER BY id"
  BAD=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE (id IN ($LIST) OR name IN ($LIST)) AND (id NOT IN ($LIST) OR active OR \"activeVersionId\" IS NOT NULL OR \"isArchived\")")
  echo "rows that refuse a re-import (foreign id, active, published or archived): $BAD"
  [[ "$BAD" == "0" ]] || fail "re-import allowed only over INACTIVE fabric ids; stop and report (09_rollback.sh unpublishes)"
  for id in "${IDS[@]}"; do
    E=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$id'")
    [[ "$E" == "0" ]] && echo "  plan: $id  CREATE (absent; imported inactive)" || echo "  plan: $id  REPLACE (inactive; re-imported over, still inactive)"
  done
fi

echo "== 6. relay credential exists (id/type only) and relay listening"
CRED=$("${PSQL[@]}" -c "SELECT id||'|'||type FROM credentials_entity WHERE id='tradeai-run-relay'")
[[ "$CRED" == "tradeai-run-relay|httpHeaderAuth" ]] || fail "credential tradeai-run-relay missing"
ss -ltn | grep -q '172.19.0.1:18092' || fail "relay not listening"
echo "n8n active workflows now: $("${PSQL[@]}" -c 'SELECT count(*) FROM workflow_entity WHERE active')"
echo "PREFLIGHT OK"
