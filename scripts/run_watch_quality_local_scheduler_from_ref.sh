#!/usr/bin/env bash
set -euo pipefail

readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${WATCH_QUALITY_SOURCE_REF:-}"
readonly MODE="${WATCH_QUALITY_SCHEDULER_MODE:-DRY_RUN}"
readonly LIMIT="${WATCH_QUALITY_LOCAL_LIMIT:-20}"
readonly EVIDENCE_ROOT="${WATCH_QUALITY_EVIDENCE_ROOT:-/home/johnclaw/tradeai-audit/watch-quality}"
readonly STAGE_ROOT="$(mktemp -d /tmp/watch-quality-local-scheduler.XXXXXX)"

cleanup() {
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_GATE6: WATCH_QUALITY_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ "$MODE" != "DRY_RUN" && "$MODE" != "RUN" ]]; then
  echo "BLOCKED_GATE6: WATCH_QUALITY_SCHEDULER_MODE must be DRY_RUN or RUN" >&2
  exit 2
fi
if [[ ! "$LIMIT" =~ ^[0-9]+$ ]] || (( LIMIT < 1 || LIMIT > 40 )); then
  echo "BLOCKED_GATE6: WATCH_QUALITY_LOCAL_LIMIT must be 1..40" >&2
  exit 2
fi

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_GATE6: resolved commit differs from exact source ref" >&2
  exit 2
fi

GATE4_JSON="${WATCH_QUALITY_GATE4_JSON:-}"
if [[ -z "$GATE4_JSON" ]]; then
  GATE4_JSON="$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f \
    -name 'watch-quality-gate4-*.json' -printf '%T@ %p\n' 2>/dev/null \
    | sort -nr | awk 'NR==1 {sub(/^[^ ]+ /, ""); print; exit}')"
fi
if [[ -z "$GATE4_JSON" || ! -f "$GATE4_JSON" ]] \
   || ! grep -Fq '"status": "PASS_GATE4_READONLY_VERIFICATION"' "$GATE4_JSON"; then
  echo "BLOCKED_GATE6: passing Gate 4 evidence not found" >&2
  exit 2
fi

BUILD_META="$HOST_REPO/apps/command-center-v3/dist/build-meta.json"
if [[ ! -f "$BUILD_META" ]]; then
  echo "BLOCKED_GATE6: live build-meta.json unavailable" >&2
  exit 2
fi
python3 - "$BUILD_META" "$RESOLVED_COMMIT" <<'PY'
import json
import sys
from pathlib import Path
payload = json.loads(Path(sys.argv[1]).read_text())
expected = sys.argv[2]
if payload.get("source_commit") != expected:
    raise SystemExit("BLOCKED_GATE6: live UI source commit differs from scheduler source")
if payload.get("watch_quality_contract") != "watch-quality-governance-v1":
    raise SystemExit("BLOCKED_GATE6: live UI lacks watch-quality-governance-v1")
PY

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

printf 'scheduler_source_commit|%s\n' "$RESOLVED_COMMIT"
printf 'scheduler_mode|%s\n' "$MODE"
printf 'local_limit|%s\n' "$LIMIT"
printf 'gate4_evidence|%s\n' "$GATE4_JSON"
printf 'oauth_lane|WITHHELD\n'
printf 'paid_lane|WITHHELD\n'

cd "$STAGE_ROOT"
if [[ "$MODE" == "DRY_RUN" ]]; then
  PYTHONPATH="$STAGE_ROOT/scripts:$STAGE_ROOT/scripts/lib" \
  "$PY" "$STAGE_ROOT/scripts/watch_quality_local_scheduler.py" \
    --dry-run --limit "$LIMIT"
else
  WATCH_QUALITY_LOCAL_SCHEDULER_ACK=ACTIVATE_BOUNDED_LOCAL_QUANT \
  PYTHONPATH="$STAGE_ROOT/scripts:$STAGE_ROOT/scripts/lib" \
  "$PY" "$STAGE_ROOT/scripts/watch_quality_local_scheduler.py" \
    --run --limit "$LIMIT"
fi
