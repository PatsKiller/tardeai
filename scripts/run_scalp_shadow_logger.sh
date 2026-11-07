#!/usr/bin/env bash
# M3-S3 intraday shadow logger — score the scalp universe as-of the current RTH minute and log to
# scalp_ignition_events. SHADOW: no alerts, no proposals (the module has no such code). Read-only vs
# the trading system; writes only its own table.
# Schedule (RTH only) — NOT installed by default; enable on operator OK, e.g. every 5 min 09:30-16:00 ET:
#   */5 9-15 * * 1-5  cd $PROJ && bash scripts/run_scalp_shadow_logger.sh >> logs/scalp_shadow_logger.log 2>&1
#   0,5..55 16 ...    (16:00 handled by the 9-15 range ending; add a 16:00 line if wanted)
set -euo pipefail
# Resolve the tree from this script's own location, never a hardcoded checkout: the live cron line runs the copy in
# the canonical tree (same result as before), while an n8n run executes the code root it was started from. A
# hardcoded path would make an n8n cutover of this lane run the served tree and still exit 0 — a cutover that looks
# like a success and changes nothing.
PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"
TOT=$("$PROJ/.venv/bin/python" -c "import json;d=json.load(open('data/portfolios/state/holdings.json'));print(d['portfolio_totals']['total_value'])" 2>/dev/null || echo 0)
if [ "$(printf '%.0f' "$TOT" 2>/dev/null || echo 0)" -le 0 ]; then
  echo "$(date -Is) ABORT: holdings total_value=$TOT (IRON RULE)"; exit 1
fi
if [ -f "$HOME/.tradeai/SCALP_ENGINE_DISABLED" ]; then
  echo "$(date -Is) HALT: kill file present"; exit 0
fi
# A --dry-run run takes the dry-run lock, never the live one. n8n_run_executor.lock_path_for does the same for every
# lane (DRY_RUN_LOCK_SUFFIX, 2026-10-11 LOCK_STEAL): a shadow fire that held the live lock would make the real cron
# line skip, so a run that writes nothing would still cost a live run. The name matches what the executor uses.
LOCK=/tmp/scalp_shadow_logger.lock
for a in "$@"; do
  if [ "$a" = "--dry-run" ]; then LOCK="$LOCK.dryrun"; fi
done
exec bash "$PROJ/scripts/safe_flock.sh" "$LOCK" \
  "$PROJ/.venv/bin/python" scripts/scalp_shadow_logger.py --live --apply --top 0 "$@"
