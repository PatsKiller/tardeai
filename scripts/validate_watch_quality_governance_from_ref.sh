#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="WATCH_QUALITY_VALIDATION_ONLY"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly STAGE_ROOT="$(mktemp -d /tmp/watch-quality-validation.XXXXXX)"
readonly TAR="$(command -v tar)"
readonly NPM="$(command -v npm)"
readonly NPX="$(command -v npx)"
readonly PYTHON_DEFAULT="$(command -v python3)"

cleanup() { rm -rf "$STAGE_ROOT"; }
trap cleanup EXIT

if [[ "${VALIDATION_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_WATCH_QUALITY_VALIDATION: VALIDATION_ACK must equal $ACK_REQUIRED" >&2; exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_WATCH_QUALITY_VALIDATION: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2; exit 2
fi
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_WATCH_QUALITY_VALIDATION: repository unavailable: $HOST_REPO" >&2; exit 2
fi
for required in "$TAR" "$NPM" "$NPX" "$PYTHON_DEFAULT"; do
  [[ -n "$required" && -x "$required" ]] || { echo "BLOCKED_WATCH_QUALITY_VALIDATION: required existing command unavailable" >&2; exit 2; }
done

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
[[ "$RESOLVED_COMMIT" == "$SOURCE_REF" ]] || { echo "BLOCKED_WATCH_QUALITY_VALIDATION: resolved commit differs from exact source ref" >&2; exit 2; }

git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" \
  .github/workflows/watch-quality-governance-ci.yml \
  apps/command-center-v3 config/watch_quality_policy.json config/research_due_diligence_policy.json \
  docs/operations/MAYA_INTELLIGENCE_AUTHORITY_MATRIX_2026-07-25.md scripts \
  tests/test_watch_quality_policy.py tests/test_strategy_ticket_quality_gate.py \
  tests/test_strategy_ticket_review_contract.py tests/test_strategy_ticket_reconciler_v11.py \
  tests/test_watch_packet_quality.py tests/test_watch_quality_scheduler_contract.py \
  tests/test_watch_quality_audit_contract.py tests/test_watch_quality_projection.py \
  tests/test_watch_quality_projection_v2.py tests/test_watch_quality_gate3_contract.py \
  tests/test_watch_quality_gate4_contract.py tests/test_watch_quality_gate5_contract.py \
  tests/test_watch_quality_gate6_contract.py tests/test_watch_quality_gate6_bound_contract.py \
  tests/test_watch_quality_rollout_orchestrator.py \
  tests/test_watch_quality_ui_contract.py tests/test_ticket_review_worker_fail_closed.py \
  tests/test_validate_watch_quality_governance_from_ref.py tests/test_research_due_diligence.py \
  tests/test_research_due_diligence_census.py tests/test_maya_intelligence_contract.py \
  tests/test_maya_intelligence_audit_contract.py | "$TAR" -x -C "$STAGE_ROOT"

readonly PY="$([[ -x "$HOST_REPO/.venv/bin/python" ]] && printf '%s' "$HOST_REPO/.venv/bin/python" || printf '%s' "$PYTHON_DEFAULT")"
cd "$STAGE_ROOT"
"$PY" -m py_compile \
  scripts/watch_quality_policy.py scripts/watch_packet_quality.py \
  scripts/watch_quality_projection.py scripts/watch_quality_projection_v2.py \
  scripts/watch_quality_governed_builder.py \
  scripts/watch_quality_gate3_sample_rebuild.py scripts/watch_quality_gate3_sample_rebuild_v2.py \
  scripts/watch_quality_gate4_verify.py scripts/watch_quality_local_scheduler.py \
  scripts/watch_quality_gate6_selection.py scripts/watch_quality_gate6_bound_scheduler.py \
  scripts/strategy_ticket_validator.py scripts/strategy_ticket_review.py \
  scripts/strategy_ticket_reconciler.py scripts/run_ticket_review_job.py \
  scripts/watch_decision_scheduler.py scripts/watch_quality_audit.py \
  scripts/research_due_diligence.py scripts/research_due_diligence_census.py \
  scripts/specialized_research_due_diligence.py scripts/specialized_research_pipeline.py \
  scripts/sector_momentum_engine_v5.py scripts/maya_intelligence_contract.py

"$PY" -m pytest -q \
  tests/test_watch_quality_policy.py tests/test_strategy_ticket_quality_gate.py \
  tests/test_strategy_ticket_review_contract.py tests/test_strategy_ticket_reconciler_v11.py \
  tests/test_watch_packet_quality.py tests/test_watch_quality_scheduler_contract.py \
  tests/test_watch_quality_audit_contract.py tests/test_watch_quality_projection.py \
  tests/test_watch_quality_projection_v2.py tests/test_watch_quality_gate3_contract.py \
  tests/test_watch_quality_gate4_contract.py tests/test_watch_quality_gate5_contract.py \
  tests/test_watch_quality_gate6_contract.py tests/test_watch_quality_gate6_bound_contract.py \
  tests/test_watch_quality_rollout_orchestrator.py \
  tests/test_watch_quality_ui_contract.py tests/test_ticket_review_worker_fail_closed.py \
  tests/test_validate_watch_quality_governance_from_ref.py tests/test_research_due_diligence.py \
  tests/test_research_due_diligence_census.py tests/test_maya_intelligence_contract.py \
  tests/test_maya_intelligence_audit_contract.py

cd "$STAGE_ROOT/apps/command-center-v3"
"$NPM" ci
"$NPX" tsc --pretty false
"$NPX" vite build

markers=("watch-quality-governance-v1" "STREET DATA >7D" "OWNERSHIP ELIGIBLE" "MECHANICS VALID" "DETERMINISTIC_REVIEW_REQUIRED" "RECOMMENDED · NOT RUN")
for marker in "${markers[@]}"; do
  grep -R --binary-files=text -Fq "$marker" "$STAGE_ROOT/apps/command-center-v3/dist" || { echo "BLOCKED_WATCH_QUALITY_VALIDATION: built bundle missing marker: $marker" >&2; exit 4; }
done

printf 'validated_commit|%s\n' "$RESOLVED_COMMIT"
printf 'validation_scope|TEMPORARY_BUILD_AND_TESTS_ONLY\n'
printf 'quality_policy_contract|watch-quality-admission-v1\n'
printf 'quality_projection_contract|watch-quality-projection-v2\n'
printf 'governed_builder_contract|watch-quality-governed-builder-v1\n'
printf 'projection_v1_status|SUPERSEDED_SOURCE_UNIT_CONFLICT\n'
printf 'gate3_contract|watch-quality-gate3-sample-rebuild-v1\n'
printf 'gate3_roundtrip_contract|watch-quality-gate3-jsonb-roundtrip-v1\n'
printf 'gate4_contract|watch-quality-gate4-readonly-verification-v1\n'
printf 'gate5_contract|WATCH_QUALITY_SHADOW_UI_ONLY\n'
printf 'gate6_contract|watch-quality-local-scheduler-v1\n'
printf 'gate6_population_contract|watch-quality-active-population-v1\n'
printf 'gate6_selection_contract|watch-quality-gate6-reviewed-selection-v1\n'
printf 'gate6_transaction_contract|watch-quality-local-atomic-batch-v1\n'
printf 'rollout_contract|watch-quality-rollout-gates-3-to-6-v1\n'
printf 'research_due_diligence_contract|research-due-diligence-v1\n'
printf 'cross_domain_census_contract|research-due-diligence-census-v1\n'
printf 'maya_intelligence_contract|maya-intelligence-evidence-v1\n'
printf 'specialized_domains|PROPOSAL,DEFENSE,SECTOR,INDUSTRY,WATCH\n'
printf 'review_contract|watch-ticket-independent-review-v2\n'
printf 'ui_contract|watch-quality-governance-v1\n'
printf 'live_dist_change|NONE\n'
printf 'database_write|NONE\n'
printf 'packet_rebuild|NONE\n'
printf 'model_provider_call|NONE\n'
printf 'paid_lane_call|NONE\n'
printf 'schedule_change|NONE\n'
printf 'service_restart|NONE\n'
printf 'external_action|NONE\n'
printf 'final_status|PASS_WATCH_QUALITY_GOVERNANCE_VALIDATION\n'
