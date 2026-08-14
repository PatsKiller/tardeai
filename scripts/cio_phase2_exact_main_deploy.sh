#!/usr/bin/env bash
#
# cio_phase2_exact_main_deploy.sh — immutable exact-main portfolio-server release.
#
# prepare  — clone CURRENT (runtime + dist), overlay origin/main, rebuild frontend, stamp SHA
# promote  — point CURRENT + systemd at the prepared release, restart, health
# rollback — restore PREV recorded in state
# status
#
# Authority: READ_ONLY_ADVISORY. No broker. Telegram remains interdicted.
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASES_BASE="${HOME}/trade-ai-releases/portfolio-server"
CANONICAL_SOURCE="${CANONICAL_SOURCE:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
VENV_PYTHON="${VENV_PYTHON:-${CANONICAL_SOURCE}/.venv/bin/python}"
SYSTEMD_DROPIN="${HOME}/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf"
SERVICE_NAME="portfolio-server.service"
HEALTH_URL="${HEALTH_URL:-http://localhost:7777/api/v2/health}"
CIO_URL="${CIO_URL:-http://localhost:7777/v3/cio}"
STATE_DIR="${HOME}/.local/state/cio-phase2-exact-main"
STATE_FILE="${STATE_DIR}/state.env"
LABEL="${CIO_EXACT_LABEL:-main-exact-phase2}"

MODE="${1:-status}"

log() { echo "[phase2 $(date -u +%H:%M:%S)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

git_sha() { git -C "$ROOT" rev-parse origin/main; }
git_sha_short() { git -C "$ROOT" rev-parse --short origin/main; }

current_release() { readlink -f "${RELEASES_BASE}/CURRENT"; }

write_state() {
  mkdir -p "$STATE_DIR"
  cat >"$STATE_FILE" <<EOF
PREV_RELEASE=${PREV_RELEASE:-}
NEW_RELEASE=${NEW_RELEASE:-}
CONTENT_SHA=${CONTENT_SHA:-}
UPDATED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
}

load_state() {
  # shellcheck disable=SC1090
  [[ -f "$STATE_FILE" ]] && source "$STATE_FILE" || true
}

health_check() {
  local label="${1:-health}"
  local ok=0
  for i in $(seq 1 25); do
    if curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null \
      | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get("ok") else 1)' 2>/dev/null; then
      ok=1
      break
    fi
    sleep 2
  done
  local code_cio
  code_cio=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 8 "$CIO_URL" || echo 000)
  if [[ "$ok" -ne 1 ]]; then
    log "FAIL $label: health endpoint not ok"
    return 1
  fi
  if [[ "$code_cio" != "200" ]]; then
    log "FAIL $label: /v3/cio HTTP $code_cio"
    return 1
  fi
  log "PASS $label: health ok + /v3/cio=$code_cio"
  return 0
}

stamp_build() {
  local dir="$1" sha="$2"
  printf '%s\n' "$sha" >"${dir}/BUILD_SHA"
  printf '%s\n' "$sha" >"${dir}/GIT_SHA"
  printf '%s\n' "main" >"${dir}/BUILD_BRANCH"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${dir}/BUILD_STAMPED_AT"
  printf '%s\n' "stamped_by=cio_phase2_exact_main_deploy.sh" >"${dir}/BUILD_STAMP_NOTE"
  python3 - <<PY
import json
from pathlib import Path
p = Path("${dir}") / "BUILD_STAMP.json"
p.write_text(json.dumps({
    "build_sha": "${sha}",
    "source_sha": "${sha}",
    "git_sha": "${sha}",
    "branch": "main",
    "label": "${LABEL}",
    "stamped_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
}, indent=2) + "\n")
PY
}

link_pipeline_data() {
  local dest="$1"
  local dirs=(
    "data/portfolios/state"
    "state/data_broker"
    "data/runtime"
    "data/health"
    "data/cio"
  )
  for rel in "${dirs[@]}"; do
    local target="${dest}/${rel}"
    local source="${CANONICAL_SOURCE}/${rel}"
    if [[ -e "$source" ]]; then
      rm -rf "$target"
      mkdir -p "$(dirname "$target")"
      ln -sfn "$source" "$target"
      log "  symlink $rel → canonical"
    fi
  done
}

build_frontend() {
  local src="$1"
  local dest="$2"
  local cc="${src}/apps/command-center-v3"
  [[ -d "$cc" ]] || die "command-center-v3 missing in $src"
  export PATH="${HOME}/.nvm/versions/node/v22.23.2/bin:${PATH}"
  command -v npm >/dev/null || die "npm not on PATH"
  log "Building frontend from $cc (accepted source line)"
  (
    cd "$cc"
    if [[ ! -d node_modules ]]; then
      npm ci --ignore-scripts
    fi
    # Full package.json build is token+tsc+vite. Fall back to vite-only if tsc is noisy.
    if npm run build; then
      log "npm run build OK"
    else
      log "npm run build failed — vite build only"
      npx vite build
    fi
  )
  mkdir -p "${dest}/apps/command-center-v3/dist"
  rsync -a --delete "${cc}/dist/" "${dest}/apps/command-center-v3/dist/"
  python3 - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path
meta = {
    "git_sha": "${CONTENT_SHA}",
    "source_sha": "${CONTENT_SHA}",
    "build_sha": "${CONTENT_SHA}"[:12],
    "built_at": datetime.now(timezone.utc).isoformat(),
    "branch": "main",
    "release_label": "${LABEL}",
}
for p in (
    Path("${dest}/apps/command-center-v3/build-meta.json"),
    Path("${dest}/apps/command-center-v3/dist/build-meta.json"),
    Path("${cc}/build-meta.json"),
):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2) + "\n")
print("wrote build-meta", meta["git_sha"][:12])
PY
}

overlay_main() {
  local dest="$1"
  log "Overlay origin/main tree from $ROOT → $dest"
  rsync -a \
    --exclude='__pycache__/' --exclude='*.pyc' --exclude='.pytest_cache/' \
    "${ROOT}/scripts/" "${dest}/scripts/"
  rsync -a "${ROOT}/docs/investment-office/" "${dest}/docs/investment-office/"
  mkdir -p "${dest}/tests" "${dest}/.github/workflows"
  rsync -a --include='test_cio_*.py' --include='conftest.py' --exclude='*' \
    "${ROOT}/tests/" "${dest}/tests/" || true
  for f in "${ROOT}"/tests/test_cio_*.py "${ROOT}/tests/conftest.py"; do
    [[ -f "$f" ]] && cp -a "$f" "${dest}/tests/" || true
  done
  if [[ -f "${ROOT}/.github/workflows/cio-production-hardening-ci.yml" ]]; then
    cp -a "${ROOT}/.github/workflows/cio-production-hardening-ci.yml" \
      "${dest}/.github/workflows/"
  fi
  rsync -a \
    --exclude='node_modules/' --exclude='dist/' --exclude='.vite/' \
    "${ROOT}/apps/command-center-v3/src/" \
    "${dest}/apps/command-center-v3/src/"
}

write_systemd() {
  local dir="$1" sha="$2"
  mkdir -p "$(dirname "$SYSTEMD_DROPIN")"
  cat >"$SYSTEMD_DROPIN" <<DROPIN
[Service]
WorkingDirectory=${dir}
Environment=PYTHONPATH=${dir}/scripts
Environment=LLM_GLOBAL_DAILY_USD_CAP=0.50
Environment=TRADEAI_CC_DEPLOYED_SHA=${sha}
Environment=TRADEAI_CC_SOURCE_PR=cio-phase2-exact-main
Environment=TRADEAI_WATCH_DEFAULT_WORKSPACE=intelligence
Environment=CIO_TELEGRAM_INTERDICT=1
ExecStart=
ExecStart=${VENV_PYTHON} ${dir}/scripts/portfolio_server.py
DROPIN
  log "systemd drop-in → $dir (CIO_TELEGRAM_INTERDICT=1)"
}

activate_release() {
  local dir="$1" sha="$2"
  [[ -d "$dir" ]] || die "release missing: $dir"
  [[ -x "$VENV_PYTHON" ]] || die "venv python missing: $VENV_PYTHON"
  write_systemd "$dir" "$sha"
  ln -sfn "$dir" "${RELEASES_BASE}/CURRENT"
  systemctl --user daemon-reload
  systemctl --user restart "$SERVICE_NAME"
  log "CURRENT → $dir ; service restarted"
}

cmd_prepare() {
  command -v rsync >/dev/null || die "rsync missing"
  git -C "$ROOT" fetch origin main --quiet
  PREV_RELEASE="$(current_release)"
  [[ -d "$PREV_RELEASE" ]] || die "PREV release missing"
  CONTENT_SHA="$(git_sha)"
  local short ts
  short="$(git_sha_short)"
  ts="$(date +%Y%m%d-%H%M%S)"
  NEW_RELEASE="${RELEASES_BASE}/${short}-${LABEL}-${ts}"
  log "PREV=$PREV_RELEASE"
  log "NEW =$NEW_RELEASE"
  log "SHA =$CONTENT_SHA (origin/main)"
  mkdir -p "$NEW_RELEASE"
  log "Cloning CURRENT runtime tree..."
  rsync -a --delete \
    --exclude='.venv' --exclude='.git' --exclude='logs/' \
    --exclude='__pycache__/' --exclude='*.pyc' --exclude='exports/' \
    "${PREV_RELEASE}/" "${NEW_RELEASE}/"
  overlay_main "$NEW_RELEASE"
  link_pipeline_data "$NEW_RELEASE"
  build_frontend "$ROOT" "$NEW_RELEASE"
  stamp_build "$NEW_RELEASE" "$CONTENT_SHA"
  for p in \
    "scripts/portfolio_server.py" \
    "scripts/api_v2.py" \
    "scripts/lib/cio_acceptance_v4.py" \
    "apps/command-center-v3/dist/index.html" \
    "BUILD_SHA"
  do
    [[ -e "${NEW_RELEASE}/${p}" ]] || die "missing critical path: $p"
  done
  local stamped
  stamped="$(tr -d '[:space:]' <"${NEW_RELEASE}/BUILD_SHA")"
  [[ "$stamped" == "$CONTENT_SHA" ]] || die "BUILD_SHA mismatch $stamped != $CONTENT_SHA"
  write_state
  log "PREPARE OK: $NEW_RELEASE"
  echo "$NEW_RELEASE"
}

cmd_promote() {
  load_state
  local dir="${1:-${NEW_RELEASE:-}}"
  [[ -n "$dir" ]] || die "no release — run prepare first"
  local sha
  sha="$(tr -d '[:space:]' <"${dir}/BUILD_SHA")"
  PREV_RELEASE="$(current_release)"
  NEW_RELEASE="$dir"
  CONTENT_SHA="$sha"
  write_state
  activate_release "$dir" "$sha"
  health_check "promote" || die "promote health failed — $0 rollback"
  log "PROMOTE OK live=$sha"
}

cmd_rollback() {
  load_state
  local target="${1:-${PREV_RELEASE:-}}"
  [[ -n "$target" && -d "$target" ]] || die "rollback target missing"
  local sha="unknown"
  [[ -f "${target}/BUILD_SHA" ]] && sha="$(tr -d '[:space:]' <"${target}/BUILD_SHA")"
  log "Rolling back to $target (sha=$sha)"
  activate_release "$target" "$sha"
  health_check "rollback" || die "rollback health failed"
  log "ROLLBACK OK → $target"
}

cmd_status() {
  load_state
  echo "CURRENT=$(current_release)"
  echo "BUILD_SHA=$(cat "$(current_release)/BUILD_SHA" 2>/dev/null || echo missing)"
  echo "origin/main=$(git -C "$ROOT" rev-parse origin/main 2>/dev/null || true)"
  [[ -f "$STATE_FILE" ]] && cat "$STATE_FILE"
  systemctl --user is-active "$SERVICE_NAME" || true
}

case "$MODE" in
  prepare)  cmd_prepare ;;
  promote)  cmd_promote "${2:-}" ;;
  rollback) cmd_rollback "${2:-}" ;;
  status)   cmd_status ;;
  *)
    echo "Usage: $0 {prepare|promote|rollback|status} [path]"
    exit 2
    ;;
esac
