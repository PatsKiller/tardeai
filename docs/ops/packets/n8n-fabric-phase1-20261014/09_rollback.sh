#!/usr/bin/env bash
# n8n fabric Phase 1 — rollback. Never deletes (rail 6).
#   bash 09_rollback.sh            # DRY RUN: shows the fabric rows and what would change
#   bash 09_rollback.sh --apply    # unpublish every ACTIVE fabric id, restart n8n once; needs TRADEAI_FABRIC_GRANT
# Then, if the operator wants them gone from the editor: archive (never delete) through n8n's own
# /rest/workflows/<id>/archive, exactly as ~/n8n-maturity-verification/packets/archive-16.sh does.
# Host side: promote the previous release SHA under a release-write grant. The ledger tables run_outcomes,
# effect_claims, effect_owners and comms_intents are additive and inert without the new code: leave them.
set -euo pipefail
IDS=(tradeai-fabric-run-lane tradeai-fabric-error tradeai-fabric-run-lane-probe tradeai-fabric-error-probe)
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
LIST=$(printf "'%s'," "${IDS[@]}"); LIST=${LIST%,}
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1
fail(){ echo "REFUSED: $*"; exit 1; }

"${PSQL[@]}" -F' | ' -c "SELECT id, active, \"isArchived\", coalesce(\"activeVersionId\",'NULL') FROM workflow_entity WHERE id IN ($LIST) ORDER BY id"
mapfile -t ACTIVE < <("${PSQL[@]}" -c "SELECT id FROM workflow_entity WHERE id IN ($LIST) AND (active OR \"activeVersionId\" IS NOT NULL)")
echo "active/published fabric ids: ${ACTIVE[*]:-none}"
if [[ $APPLY == 0 ]]; then
  echo "DRY RUN — would unpublish: ${ACTIVE[*]:-nothing}; then docker restart m8m-n8n (only if something was unpublished)"
  exit 0
fi
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
[[ ${#ACTIVE[@]} -gt 0 && -n "${ACTIVE[0]}" ]] || { echo "nothing active; no restart"; exit 0; }
for id in "${ACTIVE[@]}"; do
  docker exec m8m-n8n n8n unpublish:workflow --id="$id" 2>&1 | grep -v '^Postgres 16' || true
done
docker restart m8m-n8n >/dev/null
sleep 20
N=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id IN ($LIST) AND (active OR \"activeVersionId\" IS NOT NULL)")
echo "fabric ids still active/published: $N (want 0)"
[[ "$N" == "0" ]] || fail "rollback incomplete"
echo "ROLLBACK OK (grant $TRADEAI_FABRIC_GRANT)"
