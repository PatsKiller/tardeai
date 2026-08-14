#!/usr/bin/env bash
#
# cio_phase13_canary_deploy.sh — Controlled portfolio-server canary for CIO RC.
#
# Modes:
#   prepare   — create release dir only (no service touch)
#   promote   — point CURRENT + systemd at a prepared release, restart, health
#   rollback  — restore PREV release recorded in canary state
#   full      — prepare → promote → health → rollback proof → re-promote → health
#   status    — show CURRENT / canary state
#
# Design:
#   Worktree lacks apps/command-center-v3/dist (gitignored). Canary therefore
#   clones the live CURRENT release (known runtime) and OVERLAYS RC hardening
#   files from the worktree (scripts/lib/cio_*, report pipeline, api_v2 pin,
#   docs, tests). Pipeline data dirs are re-symlinked to canonical source.
#
# Authority: READ_ONLY_ADVISORY. No broker. No Telegram send.
# Does NOT set AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY.
#
set -euo pipefail

RC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RELEASES_BASE="${HOME}/trade-ai-releases/portfolio-server"
CANONICAL_SOURCE="${CANONICAL_SOURCE:-/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild}"
VENV_PYTHON="${VENV_PYTHON:-${CANONICAL_SOURCE}/.venv/bin/python}"
SYSTEMD_DROPIN="${HOME}/.config/systemd/user/portfolio-server.service.d/20-exact-sha-release.conf"
SERVICE_NAME="portfolio-server.service"
HEALTH_URL="${HEALTH_URL:-http://localhost:7777/api/v2/health}"
CIO_URL="${CIO_URL:-http://localhost:7777/v3/cio}"
STATE_DIR="${HOME}/.local/state/cio-phase13-canary"
STATE_FILE="${STATE_DIR}/state.env"
LABEL="${CIO_CANARY_LABEL:-cio-rc-phase13}"

MODE="${1:-status}"

log() { echo "[cio-canary $(date -u +%H:%M:%S)] $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null || die "missing command: $1"; }

git_sha() { git -C "$RC_ROOT" rev-parse HEAD; }
git_sha_short() { git -C "$RC_ROOT" rev-parse --short HEAD; }
git_branch() { git -C "$RC_ROOT" rev-parse --abbrev-ref HEAD; }

current_release() { readlink -f "${RELEASES_BASE}/CURRENT"; }

write_state() {
  mkdir -p "$STATE_DIR"
  cat >"$STATE_FILE" <<EOF
PREV_RELEASE=${PREV_RELEASE:-}
CANARY_RELEASE=${CANARY_RELEASE:-}
RC_SHA=${RC_SHA:-}
RC_BRANCH=${RC_BRANCH:-}
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
  for i in $(seq 1 20); do
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
  local dir="$1" sha="$2" branch="$3"
  printf '%s\n' "$sha" >"${dir}/BUILD_SHA"
  printf '%s\n' "$sha" >"${dir}/GIT_SHA"
  printf '%s\n' "$branch" >"${dir}/BUILD_BRANCH"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${dir}/BUILD_STAMPED_AT"
  printf '%s\n' "stamped_by=cio_phase13_canary_deploy.sh overlay" >"${dir}/BUILD_STAMP_NOTE"
}

overlay_rc() {
  local dest="$1"
  log "Overlay RC hardening files from $RC_ROOT → $dest"
  # Core CIO libraries + report stack
  rsync -a --delete "${RC_ROOT}/scripts/lib/" "${dest}/scripts/lib/" \
    --include='cio_*.py' --include='*/' --exclude='*' 2>/dev/null || true
  # Full lib sync of only cio_*.py without delete of non-cio
  for f in "${RC_ROOT}"/scripts/lib/cio_*.py; do
    [[ -f "$f" ]] || continue
    cp -a "$f" "${dest}/scripts/lib/"
  done
  # Explicit top-level scripts
  for rel in \
    scripts/render_cio_report_files.py \
    scripts/api_v2.py \
    scripts/cio_release_manifest.py \
    scripts/run_cio_hardening_ci.py \
    scripts/run_cio_adversarial_suite.py \
    scripts/telegram_transport.py \
    scripts/deploy_portfolio_server.sh \
    scripts/make_release.sh \
    scripts/cio_phase13_canary_deploy.sh
  do
    if [[ -f "${RC_ROOT}/${rel}" ]]; then
      mkdir -p "$(dirname "${dest}/${rel}")"
      cp -a "${RC_ROOT}/${rel}" "${dest}/${rel}"
    fi
  done
  # Docs + tests (operator evidence; not required for serve)
  if [[ -d "${RC_ROOT}/docs/investment-office" ]]; then
    mkdir -p "${dest}/docs/investment-office"
    rsync -a "${RC_ROOT}/docs/investment-office/" "${dest}/docs/investment-office/"
  fi
  if [[ -d "${RC_ROOT}/tests" ]]; then
    mkdir -p "${dest}/tests"
    rsync -a --include='test_cio_*.py' --include='conftest.py' --exclude='*' \
      "${RC_ROOT}/tests/" "${dest}/tests/" || true
    # rsync include-only is finicky; copy explicitly
    for f in "${RC_ROOT}"/tests/test_cio_*.py "${RC_ROOT}/tests/conftest.py"; do
      [[ -f "$f" ]] && cp -a "$f" "${dest}/tests/" || true
    done
  fi
  if [[ -f "${RC_ROOT}/.github/workflows/cio-production-hardening-ci.yml" ]]; then
    mkdir -p "${dest}/.github/workflows"
    cp -a "${RC_ROOT}/.github/workflows/cio-production-hardening-ci.yml" \
      "${dest}/.github/workflows/"
  fi
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
    else
      log "  skip missing canonical $rel"
    fi
  done
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
Environment=TRADEAI_CC_SOURCE_PR=cio-phase13-canary
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
  require_cmd rsync
  require_cmd git
  PREV_RELEASE="$(current_release)"
  [[ -d "$PREV_RELEASE" ]] || die "PREV release missing"
  RC_SHA="$(git_sha)"
  RC_BRANCH="$(git_branch)"
  local short
  short="$(git_sha_short)"
  local ts
  ts="$(date +%Y%m%d-%H%M%S)"
  CANARY_RELEASE="${RELEASES_BASE}/${short}-${LABEL}-${ts}"
  log "PREV=$PREV_RELEASE"
  log "NEW =$CANARY_RELEASE"
  log "RC  =$RC_SHA ($RC_BRANCH)"
  mkdir -p "$CANARY_RELEASE"
  log "Cloning CURRENT runtime tree (includes dist/)..."
  rsync -a --delete \
    --exclude='.venv' \
    --exclude='.git' \
    --exclude='logs/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='exports/' \
    "${PREV_RELEASE}/" "${CANARY_RELEASE}/"
  overlay_rc "$CANARY_RELEASE"
  link_pipeline_data "$CANARY_RELEASE"
  stamp_build "$CANARY_RELEASE" "$RC_SHA" "$RC_BRANCH"
  # Critical path checks
  for p in \
    "scripts/portfolio_server.py" \
    "scripts/api_v2.py" \
    "scripts/lib/cio_capital_plan.py" \
    "scripts/lib/cio_report_v2.py" \
    "apps/command-center-v3/dist/index.html" \
    "BUILD_SHA"
  do
    [[ -e "${CANARY_RELEASE}/${p}" ]] || die "missing critical path after prepare: $p"
  done
  write_state
  log "PREPARE OK: $CANARY_RELEASE"
  echo "$CANARY_RELEASE"
}

cmd_promote() {
  load_state
  local dir="${1:-${CANARY_RELEASE:-}}"
  local sha
  [[ -n "$dir" ]] || die "no canary release — run prepare first or pass path"
  if [[ -f "${dir}/BUILD_SHA" ]]; then
    sha="$(tr -d '[:space:]' <"${dir}/BUILD_SHA")"
  else
    sha="$(git_sha)"
  fi
  PREV_RELEASE="$(current_release)"
  CANARY_RELEASE="$dir"
  RC_SHA="$sha"
  RC_BRANCH="$(git_branch)"
  write_state
  activate_release "$dir" "$sha"
  health_check "promote" || die "promote health failed — consider: $0 rollback"
  log "PROMOTE OK"
}

cmd_rollback() {
  load_state
  local target="${1:-${PREV_RELEASE:-}}"
  [[ -n "$target" ]] || die "no PREV_RELEASE in state and no arg"
  [[ -d "$target" ]] || die "rollback target missing: $target"
  local sha="unknown"
  [[ -f "${target}/BUILD_SHA" ]] && sha="$(tr -d '[:space:]' <"${target}/BUILD_SHA")"
  log "Rolling back to $target (sha=$sha)"
  activate_release "$target" "$sha"
  health_check "rollback" || die "rollback health failed"
  log "ROLLBACK OK → $target"
}

cmd_full() {
  cmd_prepare
  load_state
  local canary="$CANARY_RELEASE"
  local prev="$PREV_RELEASE"
  log "=== FULL canary: promote → health → rollback proof → re-promote ==="
  cmd_promote "$canary"
  log "=== Rollback proof ==="
  cmd_rollback "$prev"
  log "=== Re-promote canary (leave RC live) ==="
  cmd_promote "$canary"
  # Leave CIO telegram interdicted on purpose
  log "FULL canary complete. Live Telegram remains interdicted (CIO_TELEGRAM_INTERDICT=1)."
  log "To disable interdict after operator review: edit systemd drop-in and restart."
  health_check "final"
  cat <<EOF

=== Phase 13 canary summary ===
PREV (rollback proven): $prev
CANARY (now CURRENT):   $canary
RC_SHA:                 $(cat "${canary}/BUILD_SHA")
Health:                 OK
Telegram live send:     NOT performed (interdict + no env approval)
EOF
}

cmd_status() {
  load_state
  echo "CURRENT=$(current_release)"
  echo "BUILD_SHA=$(cat "$(current_release)/BUILD_SHA" 2>/dev/null || echo missing)"
  echo "STATE_FILE=$STATE_FILE"
  if [[ -f "$STATE_FILE" ]]; then
    cat "$STATE_FILE"
  fi
  systemctl --user is-active "$SERVICE_NAME" || true
  curl -sS --max-time 5 "$HEALTH_URL" | python3 -m json.tool 2>/dev/null | head -20 || true
}

case "$MODE" in
  prepare)  cmd_prepare ;;
  promote)  cmd_promote "${2:-}" ;;
  rollback) cmd_rollback "${2:-}" ;;
  full)     cmd_full ;;
  status)   cmd_status ;;
  *)
    echo "Usage: $0 {prepare|promote|rollback|full|status} [path]"
    exit 2
    ;;
esac
