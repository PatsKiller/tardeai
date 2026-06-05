#!/usr/bin/env bash
# hermes-research-pipeline (199E skeleton, DRY_RUN default). Owner: Hermes research fleet (coordinator */15).
# Research only. No broker mutation / no live trading / no Level 7 / no GO-WAIT / no strategy scores.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "hermes-research-pipeline"
run_step "source discovery"                 "scripts/hermes_source_discovery.py"
run_step "backlog research (capped)"        "scripts/hermes_autonomous_librarian_backlog_loop.py"
run_step "catalyst research"                "scripts/catalyst_momentum_engine.py"
run_step "morning momentum-catalyst enrichment" "scripts/hermes_momentum_catalyst_morning.py"
run_step "news -> hermes bridge"            "scripts/hermes_news_bridge.py"
run_step "high-LLM queue submission"        "scripts/hermes_high_llm_enqueue.py"
pipeline_end
