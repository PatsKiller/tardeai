#!/usr/bin/env bash
# M3-S1 nightly refresh — rebuild the per-symbol intraday volume profile for the scalp universe.
# Shadow/read-only: writes ONLY to symbol_volume_profile. No orders, no proposals.
# Schedule (after market close, once daily) — NOT installed by default; enable on operator OK:
#   30 20 * * 1-5  cd $PROJ && bash scripts/run_scalp_volume_profile_refresh.sh >> logs/scalp_volume_profile.log 2>&1
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJ"
# IRON RULE: never run maintenance against a zeroed state.
TOT=$("$PROJ/.venv/bin/python" -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'])" 2>/dev/null || echo 0)
if [ "$(printf '%.0f' "$TOT" 2>/dev/null || echo 0)" -le 0 ]; then
  echo "$(date -Is) ABORT: holdings total_value=$TOT (IRON RULE)"; exit 1
fi
# Kill file (engine-wide halt, Hermes pattern)
if [ -f "$HOME/.tradeai/SCALP_ENGINE_DISABLED" ]; then
  echo "$(date -Is) HALT: kill file present, skipping refresh"; exit 0
fi
exec bash "$PROJ/scripts/safe_flock.sh" /tmp/scalp_volume_profile.lock \
  "$PROJ/.venv/bin/python" scripts/symbol_volume_profile_builder.py --from-scalp-universe --apply
