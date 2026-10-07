#!/usr/bin/env bash
# run_hermes_pipeline.sh — cron tranche B rank 7: the Hermes learning chain and the Hermes
# overnight discovery chain as manifest-driven serial stages.
#
#   --manifest config/pipelines/hermes_learning.json
#       --stage learn   proposed 10:50 daily: grader → tag engine → outcome feedback → outcome
#                       learning → score retention → config governor (today 10:50 → 11:45)
#       --stage tune    proposed 17:00 daily: autonomous self-tune
#   --manifest config/pipelines/hermes_overnight.json
#       --stage night   proposed 02:20 daily: backlog drain → universe retention → yield builder →
#                       tag-lift → industry novelty → discovery scorecard → SIEM backlog (→ 06:15)
#       --stage close   proposed 23:13 daily: commit hermes daily → source curation (23:30)
#
# Every step keeps its own `run_with_deepseek_offpeak.sh` / `llm_priority_guard.sh` wrapper and cap
# env VERBATIM inside the step command; this runner never wraps a stage in one guard (that would
# change the per-line cap accounting — study §5). NEVER_SCHEDULED skeleton; --dry-run default.
# Design + measurements: docs/implementation/n8n-parallel/proposals/cron-tranche-b-design.md
set -euo pipefail
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/_manifest_runner.sh"
manifest_pipeline_main "config/pipelines/hermes_learning.json" "$@"
