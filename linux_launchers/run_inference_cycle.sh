#!/usr/bin/env bash
# Inference Layers — cron launcher.
# Runs one full inference cycle, flock-guarded so overlapping cron ticks never
# double-run (the higher-order layer can take minutes under the LLM toll gate).
#
# Suggested crontab (PROJ/PY defined at top of crontab_backup.txt):
#   # Inference Layers — pre-open synthesis + intra-session refresh (weekdays)
#   0 8  * * 1-5 cd $PROJ && bash linux_launchers/run_inference_cycle.sh cron_preopen  >> logs/inference_cron.log 2>&1
#   0 13 * * 1-5 cd $PROJ && bash linux_launchers/run_inference_cycle.sh cron_midday   >> logs/inference_cron.log 2>&1
#   30 16 * * 1-5 cd $PROJ && bash linux_launchers/run_inference_cycle.sh cron_postclose >> logs/inference_cron.log 2>&1
set -euo pipefail
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
PY="$PROJ/.venv/bin/python"; [ -x "$PY" ] || PY="python3"
TRIGGER="${1:-cron}"
LOCK="/tmp/tradeai_inference_cycle.lock"

cd "$PROJ"
exec /usr/bin/flock -n "$LOCK" \
    timeout 25m "$PY" scripts/inference_layer_engine.py --run --trigger "$TRIGGER"
