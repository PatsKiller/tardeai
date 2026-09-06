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

# Exact-main: refuse to stamp origin/main onto a different HEAD (the hybrid disease).
require_head_is_origin_main() {
  git -C "$ROOT" fetch origin main --quiet
  local head origin_main
  head="$(git -C "$ROOT" rev-parse HEAD)"
  origin_main="$(git -C "$ROOT" rev-parse origin/main)"
  if [[ "$head" != "$origin_main" ]]; then
    die "ROOT HEAD $head != origin/main $origin_main — refuse hybrid promote. Checkout origin/main first."
  fi
  if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
    die "ROOT working tree dirty — refuse hybrid promote"
  fi
}

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
  local overlay_src
  overlay_src="$(python3 - "$ROOT" "$CANONICAL_SOURCE" <<'PY'
import os, sys
from pathlib import Path
repo, canonical = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo / "scripts"))
try:
    from lib.persistent_overlay import overlay_data_source
    print(overlay_data_source(canonical_source=canonical))
except Exception:
    print(canonical)
PY
)"
  log "  overlay data source → $overlay_src"
  # Refuse to overlay populated persistent stores onto an empty source-tree
  # data directory (SOURCE_TREE_COUPLED must not silently become empty).
  if ! python3 - "$overlay_src" "$dest" "$ROOT" <<'PY'
import sys
from pathlib import Path
src, dest, repo = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
sys.path.insert(0, str(repo / "scripts"))
try:
    from lib.persistent_overlay import overlay_is_safe
except Exception:
    sys.exit(0)
rep = overlay_is_safe(canonical_source=src, dest=dest)
if not rep.get("ok"):
    print("REFUSE_EMPTY_SOURCE_TREE_OVERLAY", rep.get("blocked"), file=sys.stderr)
    sys.exit(2)
PY
  then
    die "persistent overlay refused — canonical source is empty while dest has data"
  fi
  local dirs=(
    "data/portfolios/state"
    "state/data_broker"
    "data/runtime"
    "data/health"
    "data/cio"
    # logs/ is gitignored, so each release started it EMPTY. That orphaned more
    # than logs: claude_escalation_queue.json, health_agent.jsonl,
    # health_agent_remediation.jsonl, claude_escalation_retry_cmd.jsonl and
    # safe_flock_events.jsonl all live here. The 2026-08-27 18:48 deploy
    # abandoned an 18-entry escalation queue and restarted the health agent's
    # append-only history from zero; 147 of 160 release dirs hold such a fork.
    # It also made every "did that cron job run?" check return a false ABSENT.
    "logs"
    # Added 2026-09-05. Every one of these is a REAL DIRECTORY inside each
    # release, holding files written that same day, with NO copy under the
    # canonical root. So each deploy orphaned them, and every monitor that looked
    # at the canonical root reported the producing lane SILENT.
    #
    #   data/audit           cio_material_scan_last.json  (39KB, written 20:03)
    #                        cio_defer_revisit_last.json
    #   data/paper_trading   paper_trade_statistics_latest.json
    #   data/state           finviz_throttle.json
    #   state/hermes         hermes_api_requests.jsonl
    #
    # cio-material-scan is the clearest case: its systemd service ran at 20:03,
    # exited SUCCESS, and wrote a 39KB receipt into a directory that disappears on
    # the next promote. Copies of that receipt sit orphaned in at least four
    # superseded release dirs. AGENTS.md says exit code 0 is not evidence of work;
    # this is that failure from the other side — the work happened and the
    # evidence was thrown away.
    "data/audit"
    "data/paper_trading"
    "data/state"
    "state/hermes"
  )
  for rel in "${dirs[@]}"; do
    local target="${dest}/${rel}"
    local source="${overlay_src}/${rel}"
    if [[ -e "$source" ]]; then
      rm -rf "$target"
      mkdir -p "$(dirname "$target")"
      ln -sfn "$source" "$target"
      log "  symlink $rel → canonical"
    else
      # A missing source used to skip in silence. That is how reports/ was added
      # to this list on 2026-09-01 and linked nothing: the overlay root has no
      # reports/ (the pipeline writes it under CANONICAL_SOURCE), the test for it
      # is [[ -e ]], and a false test logged nothing at all. The release then
      # served an absent directory and the scanner read it as zero runs.
      #
      # 2026-09-05: skipping is also how a directory stays orphaned forever. A
      # path on this list is DECLARED durable, so if the canonical source does
      # not exist yet we create it and link anyway — otherwise adding a name to
      # the list above fixes nothing while looking as though it did, which is
      # exactly what happened to reports/.
      mkdir -p "$source"
      if [[ -d "$target" && ! -L "$target" ]] && compgen -G "$target/*" >/dev/null 2>&1; then
        # The release already holds release-local contents here. Two populated
        # copies is a divergence, and a machine choosing one can destroy the
        # other (AGENTS.md 0.5). Link the canonical location, and PRESERVE the
        # release-local copy under a dated name for the operator to reconcile.
        # Nothing is merged and nothing is deleted.
        local stash="${target}.release-local-$(date -u +%Y%m%dT%H%M%SZ)"
        mv "$target" "$stash"
        log "  RECONCILE $rel had release-local contents — preserved at $stash"
        log "            canonical source created empty; nothing merged, nothing deleted"
      fi
      rm -rf "$target"
      mkdir -p "$(dirname "$target")"
      ln -sfn "$source" "$target"
      log "  symlink $rel → canonical (source created)"
    fi
  done

  # reports/ is NOT persistent state: the pipeline writes run_summary.json under
  # CANONICAL_SOURCE/reports/2026-*/*/. The scalp scanner reads it through
  # PROJECT_ROOT/reports, and PROJECT_ROOT is the RELEASE dir, so without this
  # link every release serves an absent reports/ and the panel falls back to a
  # stale run (2026-09-01: run_label "1730" from the day before, empty timestamp,
  # 0 symbols scanned, while CANONICAL_SOURCE held that morning's 53-ticker run).
  local reports_src="${CANONICAL_SOURCE}/reports"
  local reports_dst="${dest}/reports"
  if [[ -e "$reports_src" ]]; then
    rm -rf "$reports_dst"
    ln -sfn "$reports_src" "$reports_dst"
    log "  symlink reports → $reports_src"
  else
    log "  WARN reports missing at $reports_src — scalp scanner will read zero runs"
  fi
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
  # Merge Vite ui_version — do not clobber it. Missing ui_version makes
  # cc-boot.js fall back to "1.6" and the desk chip render as "… · sha".
  PYTHONPATH="${ROOT}/scripts${PYTHONPATH:+:$PYTHONPATH}" \
  python3 - "$dest" "$sha" "${LABEL}" "${src_cc:-}" <<'PY'
import sys
from pathlib import Path
from lib.cc_v3_build_meta import write_merged_build_meta
dest, sha, label, extra = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
paths = [
    Path(dest) / "apps/command-center-v3/dist/build-meta.json",
    Path(dest) / "apps/command-center-v3/build-meta.json",
]
if extra:
    paths.append(Path(extra) / "build-meta.json")
    paths.append(Path(extra) / "dist/build-meta.json")
meta = write_merged_build_meta(paths, sha=sha, label=label)
print("wrote build-meta", meta.get("ui_version"), meta.get("git_sha", "")[:12])
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
  # Stamp the RELEASE only. Passing "$cc" here also wrote the source worktree's
  # tracked apps/command-center-v3/build-meta.json — and cmd_prepare calls
  # require_head_is_origin_main (:399), which dies on a dirty tree. So every
  # successful prepare dirtied the tree the NEXT prepare refuses to run on. The
  # deploy poisoned its own precondition; the only remedies were a churn commit
  # or a manual checkout, and the git history shows both.
  #
  # The $cc/dist write this drops was redundant: vite wrote that exact file
  # seconds earlier in this same function, with the same SHA — require_head_is_origin_main
  # guarantees HEAD == origin/main == CONTENT_SHA. Same shape the `stamp`
  # subcommand already uses.
  write_build_meta "$dest" "$CONTENT_SHA"
}

overlay_main() {
  local dest="$1"
  log "Overlay complete origin/main tree from $ROOT → $dest (runtime and secrets preserved)"
  # Synchronize every reviewed source/config surface so deleted files cannot
  # survive from the previous release under a new exact-main stamp. Runtime
  # state, secrets, installed dependencies, and the separately rebuilt dist
  # are deliberately protected from --delete.
  rsync -a --delete \
    --exclude='.git/' \
    --exclude='.venv/' --exclude='venv/' \
    --exclude='node_modules/' \
    --exclude='apps/command-center-v3/dist/' \
    --exclude='data/' --exclude='state/' \
    --exclude='logs/' --exclude='exports/' \
    --exclude='.env' --exclude='config/broker_credentials.env' \
    --exclude='__pycache__/' --exclude='*.pyc' \
    --exclude='.pytest_cache/' --exclude='.mypy_cache/' --exclude='.ruff_cache/' \
    "${ROOT}/" "${dest}/"
}

write_systemd() {
  local dir="$1" sha="$2"
  mkdir -p "$(dirname "$SYSTEMD_DROPIN")"
  local pr_line=""
  if [[ -n "${CIO_SOURCE_PR:-}" ]]; then
    pr_line="Environment=TRADEAI_CC_SOURCE_PR=${CIO_SOURCE_PR}"
  fi
  # Do NOT stamp CIO_TELEGRAM_INTERDICT here. Lexicographic merge used to fight
  # 25-cio-only-live.conf (20 wrote =1, 25 wrote =0). Live/interdict mode is
  # owned solely by ~/.config/systemd/user/portfolio-server.service.d/25-cio-only-live.conf
  # (or cio_telegram_mode.sh). Promote must not re-arm the kill switch.
  cat >"$SYSTEMD_DROPIN" <<DROPIN
[Service]
WorkingDirectory=${dir}
Environment=PYTHONPATH=${dir}/scripts
Environment=LLM_GLOBAL_DAILY_USD_CAP=0.50
Environment=TRADEAI_CC_DEPLOYED_SHA=${sha}
${pr_line}
Environment=TRADEAI_WATCH_DEFAULT_WORKSPACE=intelligence
ExecStart=
ExecStart=${VENV_PYTHON} ${dir}/scripts/portfolio_server.py
DROPIN
  log "systemd drop-in → $dir sha=${sha} (INTERDICT owned by 25-cio-only-live.conf; PR=${CIO_SOURCE_PR:-omitted})"
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

run_pin_check() {
  local dir="$1"
  local script="${dir}/scripts/current_pin_integrity.py"
  if [[ ! -f "$script" ]]; then
    die "current_pin_integrity.py missing in $dir — refuse hybrid"
  fi
  [[ -x "$VENV_PYTHON" ]] || die "venv python missing for pin check: $VENV_PYTHON"
  log "CURRENT pin check vs SOURCE_COMMIT in $dir"
  if ! (
    cd "$dir"
    CURRENT_PIN_DIR="$dir" CURRENT_PIN_REPO="$ROOT" \
      "$VENV_PYTHON" scripts/current_pin_integrity.py
  ); then
    die "CURRENT pin mismatch — refuse to continue (no silent hybrid)"
  fi
  log "pin check OK"
}

cmd_prepare() {
  command -v rsync >/dev/null || die "rsync missing"
  require_head_is_origin_main
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
  run_pin_check "$NEW_RELEASE"
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
  restart_root_frozen_units "$dir"
  write_deploy_receipt true promote ok false "promote_ok"
  log "PROMOTE OK live=$sha"
}

# Long-lived daemons that resolve CURRENT once, at start, and hold that concrete
# directory for their whole lifetime. A promote silently strands them on the old
# release: tradeai-health-agent ran 5d 11h against a tree promoted away on
# 2026-08-26, executing stale auto-remediation and logging 20MB into an orphaned
# logs/ dir that no CURRENT-based audit could see (2026-09-01). Restarting after
# CURRENT moves is what makes the promote actually reach them.
#
# Correctness is checked by READING BACK each unit's cwd, not by "is-active":
# the unit stays active across a promote precisely while being wrong, so
# activeness is the one signal that cannot detect this.
restart_root_frozen_units() {
  local dir="$1"
  local units="${TRADEAI_CURRENT_BOUND_UNITS:-tradeai-health-agent.service}"
  local u pid cwd
  for u in $units; do
    systemctl --user list-unit-files "$u" >/dev/null 2>&1 || { log "  skip $u (not installed)"; continue; }
    systemctl --user is-active --quiet "$u" || { log "  skip $u (not running)"; continue; }
    if ! systemctl --user restart "$u" 2>/dev/null; then
      log "  WARN $u restart failed — it may still serve the PREVIOUS release"
      continue
    fi
    sleep 3
    pid="$(systemctl --user show -p MainPID --value "$u" 2>/dev/null || true)"
    cwd=""
    [[ -n "$pid" && "$pid" != "0" ]] && cwd="$(readlink "/proc/${pid}/cwd" 2>/dev/null || true)"
    if [[ "$cwd" == "$dir" ]]; then
      log "  $u re-resolved → $dir"
    else
      log "  WARN $u cwd='$cwd' != '$dir' — still on a stale release"
    fi
  done
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
