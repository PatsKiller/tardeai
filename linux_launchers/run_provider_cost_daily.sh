#!/usr/bin/env bash
# Read-only daily provider-spend reconciliation. No paid traffic. No key rotation.
set -euo pipefail
ROOT="${TRADEAI_ROOT:-$HOME/trade-ai-releases/portfolio-server/CURRENT}"
PY="${TRADEAI_PYTHON:-$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python}"
OUT="$ROOT/data/runtime/provider_cost"
mkdir -p "$OUT"
export PROVIDER_COST_EVENT_LOG="$OUT/events.jsonl"
# Fixture replay remains the historical source of truth; live export-by-key
# fails closed unless an operator CSV is present.
cd "$ROOT"
"$PY" "$ROOT/scripts/provider_cost_reconcile.py" \
  --fixture "$ROOT/scripts/lib/provider_cost/fixtures/period_ab.json" \
  --out "$OUT/latest_reconciliation.json" \
  >"$OUT/daily.log" 2>&1 || true
"$PY" "$ROOT/scripts/provider_cost_export.py" \
  --start "$(date -u -d '1 day ago' +%Y-%m-%dT00:00:00Z 2>/dev/null || date -u +%Y-%m-%dT00:00:00Z)" \
  --end "$(date -u +%Y-%m-%dT00:00:00Z)" \
  --group-by key --format json \
  >"$OUT/export_by_key.json" 2>&1 || true
echo "provider-cost daily $(date -u +%FT%TZ)" >>"$OUT/daily.log"
