#!/usr/bin/env bash
# M3-S4 outcome backfill + dashboard regen. Fills MFE/MAE/hit_1r on resolvable shadow events
# (fired >31 min ago) and rebuilds the read-only dashboard. Read-only vs the trading system.
# Schedule (after logging window; events resolve 30 min after each fire) — NOT installed by default:
#   15,45 10-13 * * 1-5  cd $PROJ && bash scripts/run_scalp_outcome_backfill.sh >> logs/scalp_outcome_backfill.log 2>&1
set -euo pipefail
PROJ="/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild"
cd "$PROJ"
TOT=$("$PROJ/.venv/bin/python" -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'])" 2>/dev/null || echo 0)
if [ "$(printf '%.0f' "$TOT" 2>/dev/null || echo 0)" -le 0 ]; then
  echo "$(date -Is) ABORT: holdings total_value=$TOT (IRON RULE)"; exit 1
fi
if [ -f "$HOME/.tradeai/SCALP_ENGINE_DISABLED" ]; then
  echo "$(date -Is) HALT: kill file present"; exit 0
fi
bash "$PROJ/scripts/safe_flock.sh" /tmp/scalp_outcome_backfill.lock \
  "$PROJ/.venv/bin/python" scripts/scalp_shadow_outcome_backfill.py --apply
exec "$PROJ/.venv/bin/python" scripts/scalp_shadow_rollup.py --html
