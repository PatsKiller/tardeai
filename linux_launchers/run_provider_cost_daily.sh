#!/usr/bin/env bash
# Read-only daily provider-spend reconciliation. No paid traffic. No key rotation.
set -euo pipefail
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in --dry-run) DRY_RUN=1 ;; *) echo "unknown argument: $arg" >&2; exit 2 ;; esac
done
if (( DRY_RUN )); then
  echo "DRY-RUN provider-cost-reconcile: would reconcile fixture ledger and export existing provider cost evidence; no key/network access or files; inputs NOT_MEASURED"
  exit 0
fi
ROOT="${TRADEAI_ROOT:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
PY="${TRADEAI_PYTHON:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
OUT="$ROOT/data/runtime/provider_cost"
mkdir -p "$OUT"
export PROVIDER_COST_EVENT_LOG="$OUT/events.jsonl"
# Fixture replay remains the historical source of truth; live export-by-key
# fails closed unless an operator CSV is present.
cd "$ROOT"
STATUS=0
step_receipt() {
  local step="$1" rc="$2"
  "$PY" "$ROOT/scripts/completion_compound_receipt.py" --lane provider-cost-reconcile --step "$step" --exit "$rc" || STATUS=1
  if (( rc != 0 )); then STATUS=1; fi
}
RC=0
"$PY" "$ROOT/scripts/provider_cost_reconcile.py" \
  --fixture "$ROOT/scripts/lib/provider_cost/fixtures/period_ab.json" \
  --out "$OUT/latest_reconciliation.json" \
  >"$OUT/daily.log" 2>&1 || RC=$?
step_receipt reconcile "$RC"
RC=0
"$PY" "$ROOT/scripts/provider_cost_export.py" \
  --start "$(date -u -d '1 day ago' +%Y-%m-%dT00:00:00Z 2>/dev/null || date -u +%Y-%m-%dT00:00:00Z)" \
  --end "$(date -u +%Y-%m-%dT00:00:00Z)" \
  --group-by key --format json \
  >"$OUT/export_by_key.json" 2>&1 || RC=$?
step_receipt export "$RC"
echo "provider-cost daily $(date -u +%FT%TZ)" >>"$OUT/daily.log"
"$PY" "$ROOT/scripts/completion_compound_receipt.py" --lane provider-cost-reconcile --exit "$STATUS" || STATUS=1
exit "$STATUS"
