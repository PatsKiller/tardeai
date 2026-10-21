#!/usr/bin/env bash
# Inference ensemble job worker — drains queued inference_ensemble_jobs (runs the
# 3 free LLM lanes off the dashboard request path). flock-guarded so overlapping
# cron ticks never double-run; bounded per tick.
#
# Cron (every 3 min during market hours + a couple off-hours sweeps):
#   */3 9-16 * * 1-5 cd $PROJ && bash linux_launchers/run_ensemble_worker.sh
set -uo pipefail
# n8n onboarding (lane disposition 2026-10-15, MIGRATE_N8N): --dry-run anywhere in argv is an OFFLINE plan and
# wins over every live mode. It exits here, before any env/venv load, mkdir, log, lock, model, DB or process
# action, with the plan on stdout and one LaneOutput@v1 line on stderr (produced 0, empty_reason dry_run).
for _dr_a in "$@"; do
  [ "$_dr_a" = "--dry-run" ] || continue
  echo "DRY-RUN run-ensemble-worker: would take the ensemble worker flock and run scripts/inference_ensemble_worker.py --run --limit 5 (free-lane multi-LLM jobs) under an 8 minute timeout, appending to logs/ensemble_worker.log; argv=$*; dry-run wins over live flags; nothing executed or written"
  printf 'LANE_OUTPUT {"attempted_count": 0, "empty_reason": "dry_run", "lane_id": "%s", "mode": "dry_run", "pid": %d, "produced_count": 0, "schema": "LaneOutput@v1", "skipped_reasons": {}, "unit": "%s"}\n' \
    "run-ensemble-worker" "$$" "ensemble_job" >&2
  exit 0
done

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
. "$PROJ/scripts/lib/venv_python.sh"; PY="$(tradeai_venv_python "$PROJ")"  # release dirs ship no .venv
cd "$PROJ"
exec /usr/bin/flock -n /tmp/tradeai_ensemble_worker.lock \
    timeout 8m "$PY" scripts/inference_ensemble_worker.py --run --limit 5 \
    >> logs/ensemble_worker.log 2>&1
