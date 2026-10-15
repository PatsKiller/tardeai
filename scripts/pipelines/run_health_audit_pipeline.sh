#!/usr/bin/env bash
# run_health_audit_pipeline.sh — consolidation C3 (lane disposition 2026-10-15): WS2 family F36, the health/audit
# plane, as manifest-driven serial stages (config/pipelines/health_audit.json, PipelineManifest@v1).
#
#   --stage morning     proposed 07:30 weekdays: alert_missing_conditions -> write_state_freshness_history ->
#                       portfolio_level_qa -> classifier_health_check (today four lines at 07:15/07:30/07:40/07:55)
#
# NEVER_SCHEDULED skeleton: nothing in crontab or systemd calls this. --dry-run (default) prints the plan and
# executes nothing; --apply executes the manifest steps VERBATIM (each with its own flock, log and the env names its
# own cron line had). The multi-slot F36 members and the host-only ones are listed under "deferred"/"excluded" in the
# manifest and are never steps. Flip packet: docs/ops/packets/consolidation-health-audit-c3-20261015/.
set -euo pipefail
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/_manifest_runner.sh"
manifest_pipeline_main "config/pipelines/health_audit.json" "$@"
