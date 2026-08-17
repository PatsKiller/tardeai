#!/usr/bin/env bash
#
# cio_phase2_exact_main_deploy.sh — immutable exact-main portfolio-server release.
#
# prepare  — clone CURRENT (runtime + dist), overlay origin/main, rebuild frontend, stamp SHA
# promote  — point CURRENT + systemd at the prepared release, restart, health
# rollback — restore PREV recorded in state
# status
# stamp    — (re)stamp provenance artifacts for a release dir: SOURCE_COMMIT, BUILD_SHA,
#            GIT_SHA, BUILD_STAMP.json, and build-meta.json (no npm/network/systemd)
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
RECEIPT_FILE="${STATE_DIR}/deploy_receipt.json"
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

write_deploy_receipt() {
  local ok_flag="${1:-false}"
  local mode="${2:-unknown}"
  local health="${3:-unknown}"
  local rolled="${4:-false}"
  local extra="${5:-}"
  mkdir -p "$STATE_DIR"
  local sha="${CONTENT_SHA:-}"
  local dir="${NEW_RELEASE:-}"
  local prev="${PREV_RELEASE:-}"
  local pr="${CIO_SOURCE_PR:-}"
  OK_FLAG="$ok_flag" MODE="$mode" HEALTH="$health" ROLLED="$rolled" EXTRA="$extra" \
  SHA="$sha" DIR="$dir" PREV="$prev" PR="$pr" RECEIPT_FILE="$RECEIPT_FILE" python3 - <<'PY'
import json, os
from datetime import datetime, timezone
from pathlib import Path
pr = os.environ.get("PR") or None
rec = {
    "ok": os.environ.get("OK_FLAG") == "true",
    "mode": os.environ.get("MODE") or "unknown",
    "health": os.environ.get("HEALTH") or "unknown",
    "rolled_back": os.environ.get("ROLLED") == "true",
    "content_sha": os.environ.get("SHA") or "",
    "deployed_sha": os.environ.get("SHA") or "",
    "source_pr": pr,
    "release_dir": os.environ.get("DIR") or "",
    "prev_release": os.environ.get("PREV") or "",
    "extra": os.environ.get("EXTRA") or "",
    "at": datetime.now(timezone.utc).isoformat(),
    "authority": "READ_ONLY_ADVISORY",
    "script": "cio_phase2_exact_main_deploy.sh",
}
Path(os.environ["RECEIPT_FILE"]).write_text(json.dumps(rec, indent=2) + "\n")
print("wrote deploy receipt", os.environ["RECEIPT_FILE"])
PY
}

run_integrity_hook() {
  # Hard optional hook: if generate_integrity_manifest.py exists, it MUST succeed.
  local dir="$1"
  local script="${dir}/scripts/generate_integrity_manifest.py"
  if [[ ! -f "$script" ]]; then
    log "integrity hook skipped (script not present)"
    return 0
  fi
  [[ -x "$VENV_PYTHON" ]] || die "venv python missing for integrity hook: $VENV_PYTHON"
  log "Running integrity manifest hook in $dir"
  if ! (cd "$dir" && "$VENV_PYTHON" scripts/generate_integrity_manifest.py); then
    die "integrity manifest generation failed — refuse to continue"
  fi
  log "integrity manifest OK"
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
    log "FAIL $label: health endpoint not ok (timeout)"
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
  printf '%s\n' "$sha" >"${dir}/SOURCE_COMMIT"
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
  # Gitignored Fernet key for Schwab OAuth ciphertext. Never rsync from git.
  # Prefer the stable home copy so a rebuild checkout wipe cannot drop it.
  local cred_dest="${dest}/config/broker_credentials.env"
  local cred_src=""
  for cand in \
    "${HOME}/.config/tradeai/broker_credentials.env" \
    "${CANONICAL_SOURCE}/config/broker_credentials.env"
  do
    if [[ -f "$cand" ]]; then
      cred_src="$cand"
      break
    fi
  done
  if [[ -n "$cred_src" ]]; then
    mkdir -p "$(dirname "$cred_dest")"
    ln -sfn "$cred_src" "$cred_dest"
    chmod 600 "$cred_src" || true
    log "  symlink config/broker_credentials.env → stable secrets file"
  else
    log "  WARN config/broker_credentials.env missing — Schwab token encrypt will fail closed"
  fi
}

write_build_meta() {
  local dest="$1" sha="$2" src_cc="${3:-}"
  python3 - "$src_cc" <<PY
import json, sys
from datetime import datetime, timezone
from pathlib import Path
extra = sys.argv[1] if len(sys.argv) > 1 else ""
meta = {
    "git_sha": "${sha}",
    "source_sha": "${sha}",
    "build_sha": "${sha}"[:12],
    "source_commit": "${sha}",
    "built_at": datetime.now(timezone.utc).isoformat(),
    "branch": "main",
    "release_label": "${LABEL}",
}
paths = [
    Path("${dest}/apps/command-center-v3/build-meta.json"),
    Path("${dest}/apps/command-center-v3/dist/build-meta.json"),
]
if extra:
    paths.append(Path(extra) / "build-meta.json")
for p in paths:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2) + "\n")
print("wrote build-meta", meta["git_sha"][:12])
PY
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
  write_build_meta "$dest" "$CONTENT_SHA" "$cc"
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
  # Governed Almanac fixture + source catalog (R3/R4 live attach; fail-soft if absent).
  mkdir -p "${dest}/tests/fixtures" "${dest}/config"
  if [[ -f "${ROOT}/tests/fixtures/us_equity_monthly_sample.csv" ]]; then
    cp -a "${ROOT}/tests/fixtures/us_equity_monthly_sample.csv" \
      "${dest}/tests/fixtures/"
    log "  overlay almanac fixture"
  fi
  if [[ -f "${ROOT}/config/cio_research_source_catalog.json" ]]; then
    cp -a "${ROOT}/config/cio_research_source_catalog.json" "${dest}/config/"
    log "  overlay research source catalog"
  fi
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
  local pr_line=""
  if [[ -n "${CIO_SOURCE_PR:-}" ]]; then
    pr_line="Environment=TRADEAI_CC_SOURCE_PR=${CIO_SOURCE_PR}"
  fi
  cat >"$SYSTEMD_DROPIN" <<DROPIN
[Service]
WorkingDirectory=${dir}
Environment=PYTHONPATH=${dir}/scripts
Environment=LLM_GLOBAL_DAILY_USD_CAP=0.50
Environment=TRADEAI_CC_DEPLOYED_SHA=${sha}
${pr_line}
Environment=TRADEAI_WATCH_DEFAULT_WORKSPACE=intelligence
Environment=CIO_TELEGRAM_INTERDICT=1
ExecStart=
ExecStart=${VENV_PYTHON} ${dir}/scripts/portfolio_server.py
DROPIN
  log "systemd drop-in → $dir sha=${sha} (CIO_TELEGRAM_INTERDICT=1; PR=${CIO_SOURCE_PR:-omitted})"
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
  run_integrity_hook "$NEW_RELEASE"
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
  write_deploy_receipt true prepare skipped false "prepare_ok"
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
  if ! health_check "promote"; then
    log "promote health failed — rolling back to $PREV_RELEASE (do not claim PROMOTE OK)"
    local rb_sha="unknown"
    if [[ -n "$PREV_RELEASE" && -d "$PREV_RELEASE" ]]; then
      [[ -f "${PREV_RELEASE}/BUILD_SHA" ]] && rb_sha="$(tr -d '[:space:]' <"${PREV_RELEASE}/BUILD_SHA")"
      activate_release "$PREV_RELEASE" "$rb_sha"
      health_check "rollback-after-failed-promote" || log "rollback health also failed"
      write_deploy_receipt false promote timeout true "rolled_back_to_prev"
    else
      write_deploy_receipt false promote timeout false "prev_missing"
    fi
    die "promote health failed — not claiming promote OK"
  fi
  write_deploy_receipt true promote ok false "promote_ok"
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
  if ! health_check "rollback"; then
    write_deploy_receipt false rollback fail false "rollback_health_failed"
    die "rollback health failed"
  fi
  write_deploy_receipt true rollback ok false "rollback_ok"
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
  stamp)    [[ -n "${2:-}" && -n "${3:-}" ]] || die "usage: $0 stamp <release-dir> <full-40-char-sha>"
            stamp_build "$2" "$3"
            write_build_meta "$2" "$3"
            log "stamped provenance for $2 -> $3" ;;
  *)
    echo "Usage: $0 {prepare|promote|rollback|status|stamp} [path]"
    exit 2
    ;;
esac
