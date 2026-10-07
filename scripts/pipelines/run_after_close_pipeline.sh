#!/usr/bin/env bash
# run_after_close_pipeline.sh — cron tranche B rank 5: the post-close pipelines as three serial
# stages driven by config/pipelines/after_close.json (PipelineManifest@v1).
#
#   --stage close-capture   proposed 16:05 ET weekdays: close capture / repricing / technicals
#   --stage broker-truth    proposed 17:25 ET weekdays: READ-ONLY consumers of broker truth, after
#                           the last staggered broker sync (positions_sync 17:20); the syncs
#                           themselves are NOT steps (see manifest "excluded")
#   --stage planning        proposed 17:35 ET weekdays: entry plans, drift, sector/defense engines
#
# NEVER_SCHEDULED skeleton: nothing in crontab or systemd calls this. --dry-run (default) prints
# the plan and executes nothing; --apply executes the stage's manifest steps VERBATIM (each with
# its own lock, timeout and wrapper) and only when the stage has at least one step. No broker,
# stop, order or market_day_gate line is admissible as a step (pipeline_manifest.py refuses them).
# Design + measurements: docs/implementation/n8n-parallel/proposals/cron-tranche-b-design.md
set -euo pipefail
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/_manifest_runner.sh"
manifest_pipeline_main "config/pipelines/after_close.json" "$@"
