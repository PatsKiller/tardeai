#!/usr/bin/env bash
# hermes-learning cutover — STEP 1: the dry run (§23.21 "fix + dry run + regression"). Read-only unless --apply.
#   bash 01_dry_run.sh            # regression tests in the dev tree + served gate check + PR config plans (writes nothing)
#   bash 01_dry_run.sh --apply    # ALSO the manual n8n dry-run proof of the imported, inactive process (flow packet
#                                 # 02_verify.sh --apply; needs TRADEAI_FABRIC_GRANT; writes ledger rows only)
# Nothing here edits the crontab, a unit, the relay env or a config file.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=${REPO:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild}
PY=${PY:-$REPO/.venv/bin/python}
FLOW="$REPO/docs/ops/packets/n8n-hermes-learning-flow-20261015"
APPLY=0; [[ "${1:-}" == "--apply" ]] && APPLY=1

echo "== D1 regression (dev tree $REPO; hermetic: tmp_path ledgers, stub bridge/chokepoint)"
(cd "$REPO" && "$PY" -m pytest -q -p no:cacheprovider \
  tests/test_hermes_learning_prereqs_20261015.py \
  tests/test_n8n_fabric_hermes_learning_20261015.py \
  tests/test_hermes_learning_unblock_20261015.py \
  tests/test_effect_claim_20261014.py \
  tests/test_canary_effect_keys_20261015.py \
  tests/test_n8n_comms_intent_consumer_20261015.py \
  tests/test_n8n_run_route_20261008.py \
  tests/test_n8n_executor_env_allowlist_20261009.py \
  tests/test_alarm_coverage.py tests/test_dark_contract_guard.py)

echo "== D2 served gate check (read-only)"
"$PY" "$HERE/00_gate_check.py" --phase builds || echo "  (builds not served yet: prepare + promote under a release-write grant first)"

echo "== D3 cutover PR plans (dry run: diffs only)"
for phase in claim live promote; do
  echo "-- phase $phase"; "$PY" "$HERE/10_cutover_pr.py" --phase "$phase" --repo "$REPO" | head -60
done

echo "== D4 effect owners + flow gate (read-only)"
bash "$FLOW/05_cutover.sh" || true

if [[ $APPLY == 1 ]]; then
  echo "== D5 manual n8n DRY-RUN proof of the inactive process (flow packet 02_verify.sh --apply)"
  [[ -n "${TRADEAI_FABRIC_GRANT:-}" ]] || { echo "REFUSED: TRADEAI_FABRIC_GRANT not set"; exit 1; }
  bash "$FLOW/02_verify.sh" --apply
  echo "   expect: each p: row REQUESTED with slot_key set (gateway-validated), receipts carry offpeak{applies:false}"
else
  echo "DRY RUN done. --apply adds the manual n8n dry-run proof (flow packet 02_verify.sh --apply)."
fi
