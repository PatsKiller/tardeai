#!/usr/bin/env bash
# Inference ensemble job worker — drains queued inference_ensemble_jobs (runs the
# 3 free LLM lanes off the dashboard request path). flock-guarded so overlapping
# cron ticks never double-run; bounded per tick.
#
# Cron (every 3 min during market hours + a couple off-hours sweeps):
#   */3 9-16 * * 1-5 cd $PROJ && bash linux_launchers/run_ensemble_worker.sh
set -uo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJ/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
cd "$PROJ"
exec /usr/bin/flock -n /tmp/tradeai_ensemble_worker.lock \
    timeout 8m "$PY" scripts/inference_ensemble_worker.py --run --limit 5 \
    >> logs/ensemble_worker.log 2>&1
