#!/usr/bin/env bash
# governance-pipeline (199E skeleton, DRY_RUN default). Owner: Governance/operator-readiness.
# Read-only reporting + the silent-failure safety net. No live trading / no Level 7 / no GO-WAIT / no scores.
# NOTE: the freshness monitor + watchdog run on their own */20 and */30 crons (the safety net) and are
# surfaced here for visibility but must NOT be disabled by disabling this pipeline.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "governance-pipeline"
run_step "operator readiness report"        "scripts/report_operator_readiness_summary.py"
run_step "governance status"                "scripts/report_governance_status.py"
run_step "safety facts"                     "scripts/run_scheduled_system_facts.sh"
run_step "maturity control board"           "scripts/run_scheduled_maturity_control_board.sh"
run_step "job health"                       "scripts/system_health_agent.py"
run_step "state-of-repo snapshot"           "scripts/generate_state_of_repo_snapshot.py"
echo "  [note] freshness monitor (*/20) + watchdog (*/30) + heartbeat-receiver are the safety net — surfaced only, never disabled here."
pipeline_end
