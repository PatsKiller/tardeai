#!/usr/bin/env bash
# run_premarket_data_pipeline.sh — cron tranche B rank 6: the 05:45–07:25 premarket data producers
# as ONE serial stage driven by config/pipelines/premarket.json (PipelineManifest@v1).
#
#   --stage premarket   proposed 05:45 ET daily; steps carry a `dow` filter so the weekday-only
#                       lines keep their cadence and the daily lines keep theirs. The stage must
#                       finish before the 07:30 morning brief (market_day_gate line, NOT a step).
#
# NEVER_SCHEDULED skeleton: nothing in crontab or systemd calls this. --dry-run (default) prints
# the plan and executes nothing; --apply executes the manifest steps VERBATIM (each with its own
# lock, timeout and wrapper) and only when the stage has at least one step. Broker, stop, send,
# LLM-wrapped and dev-tree-wrapper lines are excluded by manifest (see "excluded"/"deferred").
# Design + measurements: docs/implementation/n8n-parallel/proposals/cron-tranche-b-design.md
set -euo pipefail
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/_manifest_runner.sh"
manifest_pipeline_main "config/pipelines/premarket.json" "$@"
