#!/usr/bin/env bash
set -euo pipefail

readonly ACK_REQUIRED="COMMAND_CENTER_REVIEW_VALIDATION_ONLY"
readonly REPO_DEFAULT=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild
readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"
readonly SOURCE_REF="${UI_SOURCE_REF:-}"
readonly STAGE_ROOT="$(mktemp -d /tmp/command-center-review-validation.XXXXXX)"
readonly TAR="$(command -v tar)"
readonly NPM="$(command -v npm)"
readonly NPX="$(command -v npx)"
readonly CURL="$(command -v curl)"
readonly PYTHON="$(command -v python3)"
PREVIEW_PID=""

cleanup() {
  if [[ -n "$PREVIEW_PID" ]]; then
    kill "$PREVIEW_PID" 2>/dev/null || true
    wait "$PREVIEW_PID" 2>/dev/null || true
  fi
  rm -rf "$STAGE_ROOT"
}
trap cleanup EXIT

if [[ "${VALIDATION_ACK:-}" != "$ACK_REQUIRED" ]]; then
  echo "BLOCKED_VALIDATION: VALIDATION_ACK must equal $ACK_REQUIRED" >&2
  exit 2
fi
if [[ -z "$SOURCE_REF" || ! "$SOURCE_REF" =~ ^[0-9a-f]{40}$ ]]; then
  echo "BLOCKED_VALIDATION: UI_SOURCE_REF must be an exact 40-character commit SHA" >&2
  exit 2
fi
if [[ ! -d "$HOST_REPO/.git" ]]; then
  echo "BLOCKED_VALIDATION: repository unavailable: $HOST_REPO" >&2
  exit 2
fi
for required in "$TAR" "$NPM" "$NPX" "$CURL" "$PYTHON"; do
  if [[ -z "$required" || ! -x "$required" ]]; then
    echo "BLOCKED_VALIDATION: required existing command unavailable" >&2
    exit 2
  fi
done

git -C "$HOST_REPO" cat-file -e "$SOURCE_REF^{commit}"
readonly RESOLVED_COMMIT="$(git -C "$HOST_REPO" rev-parse "$SOURCE_REF^{commit}")"
if [[ "$RESOLVED_COMMIT" != "$SOURCE_REF" ]]; then
  echo "BLOCKED_VALIDATION: resolved commit differs from exact source ref" >&2
  exit 2
fi

git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" \
  apps/command-center-v3 \
  scripts/check_design_tokens.sh \
  scripts/test_chip_scope.mjs \
  | "$TAR" -x -C "$STAGE_ROOT"

readonly APP="$STAGE_ROOT/apps/command-center-v3"
readonly BROWSERS="$STAGE_ROOT/playwright-browsers"
readonly LOG="$STAGE_ROOT/vite-preview.log"
cd "$APP"

"$NPM" ci
"$NPX" tsc --pretty false
"$NPX" vite build

markers=(
  "command-center-global-review-v1"
  "URL-addressable decision, provenance and evidence review"
  "data-command-center-modal"
  "OPEN REVIEW"
  "Review decision"
  "Open policy review"
  "command-center-structured-provenance-v1"
  "Structured provenance, freshness, directive lineage and watch memberships"
  "symbol-provenance"
)
for marker in "${markers[@]}"; do
  if ! grep -R --binary-files=text -Fq "$marker" "$APP/dist"; then
    echo "BLOCKED_VALIDATION: built bundle missing interaction marker: $marker" >&2
    exit 4
  fi
done

if [[ -n "${VALIDATION_PORT:-}" ]]; then
  if [[ ! "${VALIDATION_PORT}" =~ ^[0-9]{2,5}$ ]] || (( VALIDATION_PORT < 1024 || VALIDATION_PORT > 65535 )); then
    echo "BLOCKED_VALIDATION: VALIDATION_PORT must be an unused TCP port from 1024 through 65535" >&2
    exit 2
  fi
  readonly PORT="$VALIDATION_PORT"
else
  readonly PORT="$("$PYTHON" - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
)"
fi
readonly PREVIEW_ORIGIN="http://127.0.0.1:${PORT}"

PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" "$NPX" playwright install chromium
"$NPM" run preview -- --host 127.0.0.1 --port "$PORT" --strictPort >"$LOG" 2>&1 &
PREVIEW_PID=$!

READY=0
for _ in $(seq 1 60); do
  if ! kill -0 "$PREVIEW_PID" 2>/dev/null; then
    echo "BLOCKED_VALIDATION: Vite preview exited before readiness" >&2
    tail -n 80 "$LOG" >&2 || true
    exit 4
  fi
  # Readiness means the selected listener answered HTTP. Do not use curl -f:
  # an HTTP 404 is still proof that the exact strict-port preview process is live.
  if "$CURL" -sS --connect-timeout 1 --max-time 2 -o /dev/null "$PREVIEW_ORIGIN/"; then
    READY=1
    break
  fi
  sleep 1
done
if [[ "$READY" -ne 1 ]]; then
  echo "BLOCKED_VALIDATION: Vite preview did not answer on the reserved strict port" >&2
  tail -n 80 "$LOG" >&2 || true
  exit 4
fi
printf 'preview_ready|%s\n' "$PREVIEW_ORIGIN"

PLAYWRIGHT_BROWSERS_PATH="$BROWSERS" \
PLAYWRIGHT_BASE_URL="$PREVIEW_ORIGIN" \
  "$NPX" playwright test \
    e2e/defense-sectors-interactions.spec.ts \
    e2e/global-review-modal.spec.ts

printf 'validated_commit|%s\n' "$RESOLVED_COMMIT"
printf 'validation_scope|TEMPORARY_BUILD_AND_BROWSER_TESTS_ONLY\n'
printf 'live_dist_change|NONE\n'
printf 'service_restart|NONE\n'
printf 'producer_activation|NONE\n'
printf 'database_write|NONE\n'
printf 'broker_or_order_action|NONE\n'
printf 'global_review_contract|command-center-global-review-v1\n'
printf 'structured_evidence_contract|command-center-structured-provenance-v1\n'
printf 'final_status|PASS_COMMAND_CENTER_REVIEW_VALIDATION\n'
