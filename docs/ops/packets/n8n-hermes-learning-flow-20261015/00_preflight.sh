#!/usr/bin/env bash
# n8n fabric process hermes-learning — read-only preflight (no n8n write, no ledger write, no unit or crontab touched).
#   bash 00_preflight.sh              # first import: the process id must be ABSENT from n8n
#   bash 00_preflight.sh --reimport   # re-import: the row must be the process id, INACTIVE, unpublished, not archived
# Gates: the committed fabric set equals a fresh render and verifies; Run Lane and the fabric error workflow are
# PUBLISHED (Execute Workflow calls only published sub-workflows, n8n 2.43); the SERVED release carries the three step
# lanes in its run allowlist and registry (the gateway refuses run_lane_not_allowlisted otherwise); the relay is up.
set -euo pipefail
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
SRC=$REPO/docs/implementation/n8n-maturity/workflows/fabric
SERVED=${SERVED:-$(readlink -f "$HOME/trade-ai-releases/portfolio-server/CURRENT")}
WF=tradeai-fabric-hermes-learning
SUBS=(tradeai-fabric-run-lane tradeai-fabric-error)
LANES=(hermes-learning-outcome-grader hermes-learning-outcome-learning hermes-learning-config-governor)
PSQL=(docker exec m8m-n8n-db psql -U n8n -d n8n -tA)
fail(){ echo "REFUSED: $*"; exit 1; }
REIMPORT=0
case "${1:-}" in
  "") ;;
  --reimport) REIMPORT=1 ;;
  *) fail "usage: $0 [--reimport]" ;;
esac

echo "== 0. source tree $(git -C "$REPO" rev-parse HEAD); served release $SERVED ($(cat "$SERVED/GIT_SHA" 2>/dev/null || echo '?'))"
[[ -z "$(git -C "$REPO" status --porcelain -- "$SRC" "$REPO/config/n8n_fabric_processes.json")" ]] \
  || fail "fabric dir or process spec has uncommitted changes"

echo "== 1. generator: committed fabric set == fresh render (process graph from config/n8n_fabric_processes.json)"
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --check || fail "fabric set stale"

echo "== 2. trusted-deployer verify of the process file (graph + policy hash, node allowlist, no HTTP node)"
"$PY" "$REPO/scripts/n8n_workflow_templates.py" build-fabric --verify "$SRC/$WF.json" || fail "verify"

echo "== 3. Run Lane + fabric error workflow PUBLISHED (activeVersionId set), not archived"
for id in "${SUBS[@]}"; do
  ROW=$("${PSQL[@]}" -c "SELECT active::text||'|'||coalesce(\"activeVersionId\",'NULL')||'|'||\"isArchived\"::text FROM workflow_entity WHERE id='$id'")
  echo "  $id: active|activeVersionId|archived = ${ROW:-ABSENT}"
  [[ -n "$ROW" && "$ROW" != *"|NULL|"* && "$ROW" == *"|false" ]] || fail "$id is not published (Build 1 packet n8n-fabric-phase1-20261014)"
done

echo "== 4. served release carries the step lanes (allowlist + registry + effect keys) and the process spec"
for lane in "${LANES[@]}"; do
  "$PY" - "$SERVED" "$lane" <<'PY' || fail "served release lacks $lane: promote the merged SHA first (release-write grant)"
import json, sys
root, lane = sys.argv[1], sys.argv[2]
allow = {e["lane_id"]: e for e in json.load(open(f"{root}/config/n8n_run_allowlist.json"))["lanes"]}
reg = {r["lane_id"]: r for r in json.load(open(f"{root}/config/lane_registry.json"))["lanes"]}
eff = json.load(open(f"{root}/config/n8n_effect_keys.json"))["lanes"]
e, r = allow[lane], reg[lane]
assert e["live_arg"] is None and e["dry_run_arg"] is not None, "allowlist entry must be dry-run only"
assert r["scheduler"]["stage"] == "shadow" and "dispatch" not in r, "registry row must be stage shadow, no dispatch"
assert eff[lane]["cron_claim"] is False, "cron_claim must stay false until the cutover"
print(f"  {lane}: allowlisted (dry_run_arg {e['dry_run_arg']}, lock {e['lock']}), stage shadow, effect key ok")
PY
done
[[ -f "$SERVED/config/n8n_fabric_processes.json" ]] || fail "served release lacks config/n8n_fabric_processes.json"

if [[ $REIMPORT == 0 ]]; then
  echo "== 5. $WF absent from n8n (incl. archived)"
  N=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE id='$WF' OR name='$WF'")
  [[ "$N" == "0" ]] || fail "id/name collision ($N row): use --reimport only if it is the INACTIVE process row"
else
  echo "== 5. --reimport: the row is $WF, INACTIVE, unpublished, not archived"
  BAD=$("${PSQL[@]}" -c "SELECT count(*) FROM workflow_entity WHERE (id='$WF' OR name='$WF') AND (id<>'$WF' OR active OR \"activeVersionId\" IS NOT NULL OR \"isArchived\")")
  [[ "$BAD" == "0" ]] || fail "re-import allowed only over the INACTIVE process row (09_rollback.sh unpublishes)"
fi

echo "== 6. relay listening; the stage runner lines still present (shadow runs ALONGSIDE them)"
ss -ltn | grep -q '172.19.0.1:18092' || fail "relay not listening"
crontab -l | grep -E 'run_hermes_pipeline\.sh --stage (learn|tune) --apply' | grep -v '^#' | sed 's/^/  cron: /' \
  || fail "stage runner cron lines not found"
echo "PREFLIGHT OK"
