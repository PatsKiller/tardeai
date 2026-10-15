#!/usr/bin/env bash
# n8n fabric process hermes-learning — STEP 3: publish the process for the 5-run DRY-RUN shadow.
#   bash 03_publish_shadow.sh            # DRY RUN: preflight (--reimport rule: imported, inactive) + the plan
#   bash 03_publish_shadow.sh --apply    # needs TRADEAI_FABRIC_GRANT naming tradeai-fabric-hermes-learning
# Publishing arms the two Schedule Triggers: learn 50 10 * * * and tune 0 17 * * * (America/New_York), the same minutes
# as the stage runner's cron lines, which KEEP RUNNING (--apply) and stay the owner of every effect. The process
# requests mode dry_run (config/n8n_fabric_processes.json) and the executor clamps any live request of a stage-shadow
# lane to dry_run; a dry run takes <lock>.dryrun, so it never contends with the cron step's lock. Nothing here edits
# the crontab, a unit, the allowlist or the relay live-lanes env.
# Same day, BEFORE or right after the publish: the registry PR that flips the three step rows NEVER_SCHEDULED -> ACTIVE
# and refreshes docs/implementation/n8n-parallel/workflows/active_workflows_snapshot.json (check_lane_registry rule:
# an ACTIVE kind-n8n row needs its workflow active, and an active workflow needs a declaring row).
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
WF=tradeai-fabric-hermes-learning
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
N8N=(docker exec -e N8N_RUNNERS_BROKER_PORT=5690 m8m-n8n n8n)
fail(){ echo "REFUSED: $*"; exit 1; }
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1

bash "$HERE/00_preflight.sh" --reimport   # the row must exist INACTIVE (imported by 01), plus every other gate
[[ "$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF'")" == "1" ]] || fail "$WF not imported (01)"
HM=$(TZ=America/New_York date +%H%M)
echo "PLAN: n8n publish:workflow --id=$WF; docker restart m8m-n8n (a CLI publish loads at start); verify active."
echo "      First shadow fires: learn at the next 10:50 ET, tune at the next 17:00 ET. Now: $HM ET."
[[ $APPLY == 1 ]] || { echo "DRY RUN — nothing published"; exit 0; }
[[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || fail "TRADEAI_FABRIC_GRANT not set"
case "$HM" in 104*|105*|110*|111*|112*|113*|114*|115*|165*|170*|171*) fail "do not restart n8n inside a stage window ($HM ET)";; esac
echo "active before: $("${PSQL[@]}" -c 'SELECT count(*) FROM workflow_entity WHERE active')"
"${N8N[@]}" publish:workflow --id="$WF" 2>&1 | grep -v '^Postgres 16' || true
docker restart m8m-n8n >/dev/null
sleep 25
ROW=$("${PSQL[@]}" -c "SELECT active::text||'|'||coalesce(\"activeVersionId\",'NULL') FROM workflow_entity WHERE id='$WF'")
echo "$WF active|activeVersionId = $ROW"
[[ "$ROW" == true\|* && "$ROW" != *"|NULL" ]] || fail "publish did not take — run 09_rollback.sh"
echo "active after: $("${PSQL[@]}" -c 'SELECT count(*) FROM workflow_entity WHERE active') (before + 1)"
echo "PUBLISHED FOR SHADOW (grant $TRADEAI_FABRIC_GRANT). Evidence after each 10:50 fire: python3 $HERE/04_evidence.py --date \$(TZ=America/New_York date +%Y%m%d) --stage learn"
