#!/usr/bin/env bash
# portfolio-maintenance-pipeline (199E skeleton, DRY_RUN default). Owner: Portfolio maintenance. Off-hours.
# Read-only analysis + backups. No holdings mutation / no live trading / no Level 7 / no GO-WAIT / no scores.
source "$(dirname "${BASH_SOURCE[0]}")/_pipeline_common.sh"
pipeline_start "portfolio-maintenance-pipeline"
run_step "encrypted offsite backup (.env + data -> Drive)" "scripts/backup_secrets_state.sh"
run_step "price cache refresh"              "scripts/run_scheduled_quote_refresh.sh --cache-only"
run_step "tax/rebalance READ-ONLY analysis" "scripts/portfolio_lookthrough.py --read-only"
run_step "DB retention (per policy)"        "scripts/db_retention.py"
pipeline_end
