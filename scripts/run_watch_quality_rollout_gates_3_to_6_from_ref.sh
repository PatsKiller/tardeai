#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="EXECUTE_WATCH_QUALITY_GATES_3_TO_6"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly LIMIT="${WATCH_QUALITY_LOCAL_LIMIT:-20}"
readonly TEMP_ROOT="$(mktemp -d /tmp/watch-quality-rollout.XXXXXX)"

cleanup() {
  rm -rf "$TEMP_ROOT"
}
trap cleanup EXIT

if [[ "${WATCH_QUALITY_ROLLOUT_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_WATCH_QUALITY_ROLLOUT: WATCH_QUALITY_ROLLOUT_ACK must equal $ACK_REQUIRED" >&2
  exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_WATCH_QUALITY_ROLLOUT: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ ! "$LIMIT" =~ ^[0-9]+$ ]] || (( LIMIT < 1 || LIMIT > 40 )); then
  echo "BLOCKED_WATCH_QUALITY_ROLLOUT: WATCH_QUALITY_LOCAL_LIMIT must be 1..40" >&2
  exit 2
fi

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_WATCH_QUALITY_ROLLOUT: resolved commit differs from exact source ref" >&2
  exit 2
fi

extract() {
  local path="$1"
  local target="$2"
  git -C "$HOST_REPO" show "$RESOLVED_COMMIT:$path" > "$target"
  chmod 700 "$target"
}

VALIDATOR="$TEMP_ROOT/validate.sh"
GATE3="$TEMP_ROOT/gate3.sh"
GATE4="$TEMP_ROOT/gate4.sh"
GATE5="$TEMP_ROOT/gate5.sh"
GATE6="$TEMP_ROOT/gate6.sh"
extract scripts/validate_watch_quality_governance_from_ref.sh "$VALIDATOR"
extract scripts/run_watch_quality_gate3_from_ref.sh "$GATE3"
extract scripts/run_watch_quality_gate4_from_ref.sh "$GATE4"
extract scripts/deploy_watch_quality_ui_from_ref.sh "$GATE5"
extract scripts/install_watch_quality_local_scheduler_from_ref.sh "$GATE6"

printf 'rollout_source_commit|%s\n' "$RESOLVED_COMMIT"
printf 'rollout_contract|watch-quality-rollout-gates-3-to-6-v1\n'
printf 'local_scheduler_limit|%s\n' "$LIMIT"
printf 'model_lanes|WITHHELD\n'
printf 'oauth_lanes|WITHHELD\n'
printf 'paid_lane|WITHHELD\n'

printf '\n=== SOURCE VALIDATION ===\n'
VALIDATION_ACK=WATCH_QUALITY_VALIDATION_ONLY \
REPO="$HOST_REPO" \
WATCH_QUALITY_SOURCE_REF="$RESOLVED_COMMIT" \
bash "$VALIDATOR"

printf '\n=== GATE 3 — BOUNDED LOCAL REBUILD ===\n'
WATCH_GATE3_EXECUTION_ACK=EXECUTE_WATCH_QUALITY_GATE3 \
REPO="$HOST_REPO" \
WATCH_QUALITY_SOURCE_REF="$RESOLVED_COMMIT" \
bash "$GATE3"

printf '\n=== GATE 4 — READ-ONLY VERIFICATION ===\n'
WATCH_GATE4_EXECUTION_ACK=VERIFY_WATCH_QUALITY_GATE4 \
REPO="$HOST_REPO" \
WATCH_QUALITY_SOURCE_REF="$RESOLVED_COMMIT" \
bash "$GATE4"

printf '\n=== GATE 5 — STATIC WATCH UI ===\n'
WATCH_QUALITY_UI_DEPLOY_ACK=WATCH_QUALITY_SHADOW_UI_ONLY \
REPO="$HOST_REPO" \
WATCH_QUALITY_SOURCE_REF="$RESOLVED_COMMIT" \
bash "$GATE5"

printf '\n=== GATE 6 — LOCAL-ONLY SCHEDULER ===\n'
WATCH_QUALITY_SCHEDULE_ACK=INSTALL_AND_RUN_BOUNDED_LOCAL_QUANT \
REPO="$HOST_REPO" \
WATCH_QUALITY_SOURCE_REF="$RESOLVED_COMMIT" \
WATCH_QUALITY_LOCAL_LIMIT="$LIMIT" \
bash "$GATE6"

printf 'final_status|PASS_WATCH_QUALITY_GATES_3_TO_6\n'
