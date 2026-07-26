#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="VERIFY_WATCH_QUALITY_GATE4"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly EVIDENCE_ROOT="${WATCH_QUALITY_EVIDENCE_ROOT:-/home/johnclaw/tradeai-audit/watch-quality}"
readonly STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAGE_ROOT="$(mktemp -d /tmp/watch-quality-gate4.XXXXXX)"
readonly RESULT_JSON="$EVIDENCE_ROOT/watch-quality-gate4-$STAMP.json"
readonly SUMMARY="$EVIDENCE_ROOT/watch-quality-gate4-$STAMP.txt"

cleanup() {
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

if [[ "${WATCH_GATE4_EXECUTION_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_GATE4: WATCH_GATE4_EXECUTION_ACK must equal $ACK_REQUIRED" >&2
  exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_GATE4: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_GATE4: repository unavailable: $HOST_REPO" >&2
  exit 2
fi

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_GATE4: resolved commit differs from exact source ref" >&2
  exit 2
fi

GATE3_JSON="${WATCH_QUALITY_GATE3_JSON:-}"
if [[ -z "$GATE3_JSON" ]]; then
  GATE3_JSON="$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f \
    -name 'watch-quality-gate3-*.json' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
if [[ -z "$GATE3_JSON" || ! -f "$GATE3_JSON" ]]; then
  echo "BLOCKED_GATE4: successful Gate 3 JSON not found" >&2
  exit 2
fi
if ! grep -Fq '"status": "PASS_GATE3_BOUNDED_LOCAL_REBUILD"' "$GATE3_JSON"; then
  echo "BLOCKED_GATE4: latest Gate 3 JSON is not passing" >&2
  exit 2
fi

mkdir -p "$EVIDENCE_ROOT"
chmod 700 "$EVIDENCE_ROOT"
git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" scripts config | tar -x -C "$STAGE_ROOT"
rm -rf "$STAGE_ROOT/data"
ln -s "$HOST_REPO/data" "$STAGE_ROOT/data"
if [[ -d "$HOST_REPO/.venv" ]]; then
  ln -s "$HOST_REPO/.venv" "$STAGE_ROOT/.venv"
fi
for ENV_FILE in .env .env.local .env.production; do
  if [[ -f "$HOST_REPO/$ENV_FILE" ]]; then
    ln -s "$HOST_REPO/$ENV_FILE" "$STAGE_ROOT/$ENV_FILE"
  fi
done

PY="$HOST_REPO/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="$(command -v python3)"
fi
test -x "$PY"

{
  printf 'reviewed_commit|%s\n' "$RESOLVED_COMMIT"
  printf 'source_mode|PINNED_GIT_OBJECT_ARCHIVE\n'
  printf 'host_worktree_checkout|UNCHANGED\n'
  printf 'gate3_json|%s\n' "$GATE3_JSON"
  sha256sum \
    "$STAGE_ROOT/scripts/watch_quality_gate4_verify.py" \
    "$STAGE_ROOT/scripts/watch_quality_audit.py" \
    "$STAGE_ROOT/scripts/watch_packet_quality.py" \
    | sed 's/^/source_sha256|/'
} | tee "$SUMMARY"

cd "$STAGE_ROOT"
PYTHONPATH="$STAGE_ROOT/scripts:$STAGE_ROOT/scripts/lib" \
"$PY" "$STAGE_ROOT/scripts/watch_quality_gate4_verify.py" \
  --gate3-json "$GATE3_JSON" \
  --limit 200 \
  --sample-limit 25 \
  --evidence-json "$RESULT_JSON" \
  | tee -a "$SUMMARY"

chmod 600 "$SUMMARY" "$RESULT_JSON"
printf 'sanitized_summary|%s\n' "$SUMMARY"
printf 'sanitized_json|%s\n' "$RESULT_JSON"
printf 'final_status|PASS_GATE4_OPERATOR_PACKET\n'
