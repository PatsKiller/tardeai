#!/usr/bin/env bash
# hermes-advisory-pipeline (199E skeleton, DRY_RUN default). Owner: Hermes advisory fleet.
# NO broker mutation. Paper-only context. No live trading / no Level 7 / no GO-WAIT / no strategy scores.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "hermes-advisory-pipeline"
run_step "protection checks (OBSERVE-ONLY — workstream paused)" "scripts/run_protection_pipeline.sh --verify-only"
run_step "advisory cache worker"            "scripts/hermes_advisory_cache_worker.py"
run_step "Hermes second opinion"            "scripts/hermes_second_opinion.py"
run_step "safe-view checks (read-only)"      "scripts/hermes_observation_check.py"
pipeline_end
