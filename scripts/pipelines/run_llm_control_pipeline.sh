#!/usr/bin/env bash
# llm-control-pipeline (199E skeleton, DRY_RUN default). Owner: LLM control plane. Overnight + on-demand.
# No direct trading mutations / no live trading / no Level 7 / no GO-WAIT / no strategy scores.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "llm-control-pipeline"
run_step "build deep-overnight LLM queue"   "scripts/build_deep_overnight_llm_queue.py"
run_step "high-LLM queue scheduling/exec"   "scripts/high_llm_execution_worker.py"
run_step "deep-overnight LLM window"        "scripts/run_deep_overnight_llm_window.sh"
run_step "model allocation / retry policy"  "scripts/gpu_lifecycle.py"
run_step "failure drilldown report"         "scripts/check_deep_overnight_health.py"
pipeline_end
