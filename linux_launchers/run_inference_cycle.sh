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
TRIGGER="cron"
DRY_RUN=0
TRIGGER_SET=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    cron|cron_preopen|cron_midday|cron_postclose)
      if (( TRIGGER_SET )); then echo "repeated trigger" >&2; exit 2; fi
      TRIGGER="$arg"; TRIGGER_SET=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done
if (( DRY_RUN )); then
  echo "DRY-RUN run-inference-cycle-$TRIGGER: would tag news and run bounded inference under /tmp/tradeai_inference_cycle.lock; no interpreter, model, state or writes; inputs NOT_MEASURED"
  exit 0
fi
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
. "$PROJ/scripts/lib/venv_python.sh"; PY="$(tradeai_venv_python "$PROJ")"  # release dirs ship no .venv
LOCK="/tmp/tradeai_inference_cycle.lock"

cd "$PROJ"
# Tag recently-ingested news with cross-market regions first (cheap keyword pass, no LLM) so the
# RegionalLayer reasons over real Asia/Europe/EM-tagged data instead of 0 region-tagged news.
tag_rc=0
"$PY" scripts/region_tag_news.py --hours 96 >> logs/inference_cron.log 2>&1 || tag_rc=$?
"$PY" scripts/completion_compound_receipt.py --lane "run-inference-cycle-${TRIGGER#cron_}" --step region-tag-news --exit "$tag_rc" || true
engine_rc=0
/usr/bin/flock -n -E 75 "$LOCK" \
    timeout 25m "$PY" scripts/inference_layer_engine.py --run --trigger "$TRIGGER" || engine_rc=$?
"$PY" scripts/completion_compound_receipt.py --lane "run-inference-cycle-${TRIGGER#cron_}" --step inference-engine --exit "$engine_rc" || true
status="$engine_rc"
if (( status == 0 && tag_rc != 0 )); then status="$tag_rc"; fi
"$PY" scripts/completion_compound_receipt.py --lane "run-inference-cycle-${TRIGGER#cron_}" --exit "$status" || true
exit "$status"
