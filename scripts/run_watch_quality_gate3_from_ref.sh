#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="EXECUTE_WATCH_QUALITY_GATE3"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly EVIDENCE_ROOT="${WATCH_QUALITY_EVIDENCE_ROOT:-/home/johnclaw/tradeai-audit/watch-quality}"
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAGE_ROOT="$(mktemp -d /tmp/watch-quality-gate3.XXXXXX)"
readonly RESULT_JSON="$EVIDENCE_ROOT/watch-quality-gate3-$STAMP.json"
readonly SUMMARY="$EVIDENCE_ROOT/watch-quality-gate3-$STAMP.txt"

cleanup() { rm -rf "$STAGE_ROOT"; }
trap cleanup EXIT

if [[ "${WATCH_GATE3_EXECUTION_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_GATE3: WATCH_GATE3_EXECUTION_ACK must equal $ACK_REQUIRED" >&2; exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_GATE3: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2; exit 2
fi
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_GATE3: repository unavailable: $HOST_REPO" >&2; exit 2
fi

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
[[ "$RESOLVED_COMMIT" == "$SOURCE_REF" ]] || { echo "BLOCKED_GATE3: resolved commit differs from exact source ref" >&2; exit 2; }

PROJECTION_JSON="${WATCH_QUALITY_PROJECTION_JSON:-}"
if [[ -z "$PROJECTION_JSON" ]]; then
  PROJECTION_JSON="$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f -name 'watch-quality-projection-v2-top200-*.json' -printf '%T@ %p\n' 2>/dev/null | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
[[ -n "$PROJECTION_JSON" && -f "$PROJECTION_JSON" ]] || { echo "BLOCKED_GATE3: preserved watch-quality-projection-v2 JSON not found" >&2; exit 2; }

mkdir -p "$EVIDENCE_ROOT"
chmod 700 "$EVIDENCE_ROOT"
git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" scripts config | tar -x -C "$STAGE_ROOT"
rm -rf "$STAGE_ROOT/data"
ln -s "$HOST_REPO/data" "$STAGE_ROOT/data"
[[ ! -d "$HOST_REPO/.venv" ]] || ln -s "$HOST_REPO/.venv" "$STAGE_ROOT/.venv"
for ENV_FILE in .env .env.local .env.production; do
  [[ ! -f "$HOST_REPO/$ENV_FILE" ]] || ln -s "$HOST_REPO/$ENV_FILE" "$STAGE_ROOT/$ENV_FILE"
done

PY="$HOST_REPO/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3)"
test -x "$PY"

{
  printf 'reviewed_commit|%s\n' "$RESOLVED_COMMIT"
  printf 'source_mode|PINNED_GIT_OBJECT_ARCHIVE\n'
  printf 'host_worktree_checkout|UNCHANGED\n'
  printf 'projection_json|%s\n' "$PROJECTION_JSON"
  printf 'blind_model_system|DISABLED\n'
  printf 'inline_ticket_critic|DISABLED\n'
  sha256sum "$STAGE_ROOT/scripts/watch_quality_gate3_sample_rebuild.py" "$STAGE_ROOT/scripts/watch_packet_quality.py" "$STAGE_ROOT/scripts/watch_quality_policy.py" "$STAGE_ROOT/scripts/strategy_ticket_validator.py" "$STAGE_ROOT/scripts/shadow_decision_service.py" "$STAGE_ROOT/config/watch_quality_policy.json" | sed 's/^/source_sha256|/'
} | tee "$SUMMARY"

cd "$STAGE_ROOT"
WATCH_GATE3_ACK=BOUNDED_LOCAL_QUANT_SAMPLE \
WATCH_QUALITY_SOURCE_COMMIT="$RESOLVED_COMMIT" \
SHADOW_DISABLE_MODELS=1 \
SHADOW_DISABLE_TICKET_CRITIC=1 \
PYTHONPATH="$STAGE_ROOT/scripts:$STAGE_ROOT/scripts/lib" \
"$PY" "$STAGE_ROOT/scripts/watch_quality_gate3_sample_rebuild.py" --projection-json "$PROJECTION_JSON" --evidence-json "$RESULT_JSON" | tee -a "$SUMMARY"

chmod 600 "$SUMMARY" "$RESULT_JSON"
printf 'sanitized_summary|%s\n' "$SUMMARY"
printf 'sanitized_json|%s\n' "$RESULT_JSON"
printf 'final_status|PASS_GATE3_OPERATOR_PACKET\n'
