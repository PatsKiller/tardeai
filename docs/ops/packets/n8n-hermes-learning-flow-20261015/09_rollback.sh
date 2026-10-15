#!/usr/bin/env bash
# n8n fabric process hermes-learning — ROLLBACK. Never deletes (rail 6).
#   bash 09_rollback.sh            # DRY RUN: shows the process row, the effect owners and what would change
#   bash 09_rollback.sh --apply    # unpublish the process if published (+ one n8n restart); move every effect owner
#                                  # that is n8n back to cron (compare-and-swap); needs TRADEAI_FABRIC_GRANT
# Shadow rollback = unpublish only: the stage runner never stopped running every step. After a cutover the operator
# also uncomments the stage cron line(s) (cron grant, backup + read-back): the RETIRED line keeps its text verbatim.
# Archive (never delete) through n8n's own /rest/workflows/<id>/archive if the row should leave the editor.
# Host side: the previous release SHA under a release-write grant; the effect_claims / effect_owners rows stay.
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
WF=tradeai-fabric-hermes-learning
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
fail(){ echo "REFUSED: $*"; exit 1; }
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1

"${PSQL[@]}" -F' | ' -c "SELECT id, active, \"isArchived\", coalesce(\"activeVersionId\",'NULL') FROM workflow_entity WHERE id='$WF'"
PUB=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF' AND (active OR \"activeVersionId\" IS NOT NULL)")
mapfile -t LANES < <("$PY" -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["lanes"]))' "$SERVED/config/n8n_effect_keys.json")
declare -a MOVE=()
for lane in "${LANES[@]}"; do
  [[ -n "$lane" ]] || continue
  CUR=$("$PY" "$SERVED/scripts/lib/effect_claim.py" show --process "$lane" | "$PY" -c 'import json,sys; o=json.load(sys.stdin)["owner"]; print("" if o is None else "%s %s" % (o["owner"], o["epoch"]))')
  echo "  owner $lane: ${CUR:-none}"
  read -r COWN CEP <<<"${CUR:-none none}"
  if [[ "$COWN" == "n8n" ]]; then MOVE+=("$lane:$CEP"); fi
done
if [[ $APPLY == 0 ]]; then
  echo "DRY RUN — would unpublish $WF: $([[ "$PUB" == "1" ]] && echo yes || echo no); would move owner n8n->cron: ${MOVE[*]:-none}"
  exit 0
fi
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
for item in "${MOVE[@]}"; do
  lane=${item%%:*}; ep=${item##*:}
  "$PY" "$SERVED/scripts/lib/effect_claim.py" set-owner --process "$lane" --owner cron --expect-epoch "$ep" \
    --by "operator:$TRADEAI_FABRIC_GRANT" --note "hermes-learning rollback"
done
if [[ "$PUB" == "1" ]]; then
  docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n unpublish:workflow --id="$WF" 2>&1 | grep -v '^Postgres 16' || true
  docker restart m8m-n8n >/dev/null
  sleep 20
fi
N=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF' AND (active OR \"activeVersionId\" IS NOT NULL)")
echo "$WF still active/published: $N (want 0)"
[[ "$N" == "0" ]] || fail "rollback incomplete"
echo "ROLLBACK OK (grant $TRADEAI_FABRIC_GRANT). If a stage cron line was retired, uncomment it now (cron grant)."
