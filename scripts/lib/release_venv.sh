# shellcheck shell=bash
#
# release_venv.sh — shared, lock-hash-keyed Python venv for portfolio-server releases (run-from-release P0).
#
# Design: ~/n8n-maturity-verification/arch-review-20261014/designs/RUN_FROM_RELEASE.md §2.
# Sourced by scripts/cio_phase2_exact_main_deploy.sh; the tests source it directly.
#
#   release_venv_plan   <release-dir>   DRY: print the venv id, lock hash and build|reuse; writes nothing
#   ensure_release_venv <release-dir>   build or reuse <base>/<id>, link <release-dir>/.venv -> it
#
# Key:  <id> = py<X.Y.Z>-<sha256(requirements.lock.txt)[:12]>, under ${TRADEAI_RELEASE_VENVS_BASE}
#       (default ~/trade-ai-releases/venvs). A new lock or a new interpreter patch level is a new id, so an
#       existing venv is never modified: it is built once and reused while its id is unchanged.
#
# Interpreter: pinned by path AND minor version (TRADEAI_RELEASE_PYTHON=/usr/bin/python3.14, minor 3.14),
# never bare `python3`. 2026-10-15: the dev venv's pyvenv.cfg says 3.13.7, but its bin/python is a symlink
# to /usr/bin/python3, which an OS upgrade moved to 3.14.4; /usr/bin/python3.13 no longer exists on the host,
# and the 134-pin lock is the dev venv's own `pip freeze --all` under 3.14. So 3.14 is what production runs
# today, and pinning it changes nothing at the interpreter; a future OS move off 3.14 makes prepare refuse
# instead of silently changing the production interpreter again.
#
# Publication: the venv is built AT its final path (venv console scripts and pyvenv.cfg carry absolute
# paths, so a build-then-rename would leave every bin/ shebang pointing at the temp name). The `.complete`
# marker, written last via a same-directory rename, is the publish signal. A directory without it is a
# failed or interrupted build of THIS id: it was never linked, so it is removed and rebuilt. A failed build
# removes only its own directory; any other id's venv is untouched, and the caller (prepare) dies.
#
# Reuse is verified, not assumed: the venv's `pip freeze --all` must equal the lock byte for byte (measured
# 2026-10-15: a fresh build of the lock reproduces it exactly). A mismatch means someone ran pip in it, so it
# is no longer what the receipt says: refuse, never repair (AGENTS §0 rule 5).
#
# Writes nothing outside the venvs base and the release dir's `.venv` link. Never touches cron or units.

RELEASE_VENVS_BASE="${TRADEAI_RELEASE_VENVS_BASE:-${HOME}/trade-ai-releases/venvs}"
RELEASE_PYTHON="${TRADEAI_RELEASE_PYTHON:-/usr/bin/python3.14}"
RELEASE_PYTHON_MINOR="${TRADEAI_RELEASE_PYTHON_MINOR:-3.14}"
RELEASE_VENV_LOCK_NAME="${TRADEAI_RELEASE_VENV_LOCK_NAME:-requirements.lock.txt}"
RELEASE_VENV_SMOKE_IMPORTS="${TRADEAI_RELEASE_VENV_SMOKE_IMPORTS:-psycopg2,pandas,requests}"

# Outputs (set by release_venv_resolve / ensure_release_venv).
RELEASE_VENV_ID=""
RELEASE_VENV_DIR=""
RELEASE_VENV_LOCK_SHA256=""
RELEASE_VENV_PY_VERSION=""
RELEASE_VENV_ACTION=""
RELEASE_VENV_PYTHON=""

_rv_log() { if declare -F log >/dev/null; then log "$@"; else echo "[release-venv] $*"; fi; }
_rv_fail() { echo "ERROR: release venv: $*" >&2; return 1; }

_rv_sha256() { sha256sum "$1" | cut -c1-64; }

# Normalised freeze text for comparison. pip freeze is already sorted; this only guards line endings.
_rv_norm() { tr -d '\r' <"$1"; }

# release_venv_resolve <release-dir>: compute id/dir/action. No writes.
release_venv_resolve() {
  local dest="$1"
  local lock="${dest}/${RELEASE_VENV_LOCK_NAME}"
  [[ -f "$lock" ]] || { _rv_fail "lock file missing: $lock"; return 1; }
  [[ -s "$lock" ]] || { _rv_fail "lock file empty: $lock"; return 1; }
  [[ -x "$RELEASE_PYTHON" ]] || { _rv_fail "pinned interpreter not executable: $RELEASE_PYTHON"; return 1; }
  local ver
  ver="$("$RELEASE_PYTHON" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)" \
    || { _rv_fail "pinned interpreter failed to report its version: $RELEASE_PYTHON"; return 1; }
  [[ "$ver" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { _rv_fail "unparseable interpreter version '$ver'"; return 1; }
  if [[ "$ver" != "${RELEASE_PYTHON_MINOR}."* ]]; then
    _rv_fail "interpreter $RELEASE_PYTHON is $ver, pinned minor is ${RELEASE_PYTHON_MINOR} (refusing a silent interpreter change)"
    return 1
  fi
  RELEASE_VENV_PY_VERSION="$ver"
  RELEASE_VENV_LOCK_SHA256="$(_rv_sha256 "$lock")"
  RELEASE_VENV_ID="py${ver}-${RELEASE_VENV_LOCK_SHA256:0:12}"
  RELEASE_VENV_DIR="${RELEASE_VENVS_BASE}/${RELEASE_VENV_ID}"
  if [[ -f "${RELEASE_VENV_DIR}/.complete" ]]; then
    RELEASE_VENV_ACTION="reuse"
  elif [[ -e "${RELEASE_VENV_DIR}" ]]; then
    RELEASE_VENV_ACTION="rebuild_incomplete"
  else
    RELEASE_VENV_ACTION="build"
  fi
}

# Verify a venv dir against the lock: interpreter version and exact freeze.
_rv_verify() {
  local vdir="$1" lock="$2" ver="$3"
  local py="${vdir}/bin/python"
  [[ -x "$py" ]] || { _rv_fail "${vdir}: bin/python missing"; return 1; }
  local got
  got="$("$py" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null)" \
    || { _rv_fail "${vdir}: bin/python does not run"; return 1; }
  [[ "$got" == "$ver" ]] || { _rv_fail "${vdir}: interpreter is $got, id says $ver"; return 1; }
  local freeze
  freeze="$(mktemp "${RELEASE_VENVS_BASE}/.freeze.XXXXXX")"
  if ! "$py" -m pip freeze --all --disable-pip-version-check >"$freeze" 2>/dev/null; then
    rm -f "$freeze"; _rv_fail "${vdir}: pip freeze failed"; return 1
  fi
  if ! diff -q <(_rv_norm "$lock") <(_rv_norm "$freeze") >/dev/null; then
    local d
    d="$(diff <(_rv_norm "$lock") <(_rv_norm "$freeze") | head -10 | tr '\n' ' ')"
    rm -f "$freeze"
    _rv_fail "${vdir}: pip freeze != lock (${d}) — someone changed this venv; refusing"
    return 1
  fi
  rm -f "$freeze"
}

# Build RELEASE_VENV_DIR from the lock. On any failure remove only that (never-published) directory.
_rv_build() {
  local vdir="$1" lock="$2" ver="$3"
  local t0 rc=0
  t0="$(date +%s)"
  _rv_log "release venv: building ${vdir} (python ${ver}, lock ${RELEASE_VENV_LOCK_SHA256:0:12})"
  {
    "$RELEASE_PYTHON" -m venv "$vdir" \
      && "${vdir}/bin/python" -m pip install --disable-pip-version-check --no-input -q -r "$lock" \
      && "${vdir}/bin/python" -c "import ${RELEASE_VENV_SMOKE_IMPORTS}" \
      && _rv_verify "$vdir" "$lock" "$ver"
  } || rc=$?
  if [[ "$rc" -ne 0 ]]; then
    # Only this id's unpublished build is removed: no .complete was written, nothing links to it.
    [[ ! -f "${vdir}/.complete" ]] && rm -rf -- "$vdir"
    _rv_fail "build of ${RELEASE_VENV_ID} failed (rc=$rc); partial venv removed, other venvs untouched"
    return 1
  fi
  local marker_tmp="${vdir}/.complete.tmp"
  {
    echo "venv_id=${RELEASE_VENV_ID}"
    echo "lock_sha256=${RELEASE_VENV_LOCK_SHA256}"
    echo "python=${RELEASE_PYTHON}"
    echo "python_version=${ver}"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "build_seconds=$(( $(date +%s) - t0 ))"
  } >"$marker_tmp"
  mv -f -- "$marker_tmp" "${vdir}/.complete"
  _rv_log "release venv: built ${RELEASE_VENV_ID} in $(( $(date +%s) - t0 ))s"
}

# release_venv_plan <release-dir>: dry run. Prints key=value lines; writes nothing.
release_venv_plan() {
  local dest="$1"
  release_venv_resolve "$dest" || return 1
  echo "venv_id=${RELEASE_VENV_ID}"
  echo "venv_dir=${RELEASE_VENV_DIR}"
  echo "lock_sha256=${RELEASE_VENV_LOCK_SHA256}"
  echo "python=${RELEASE_PYTHON}"
  echo "python_version=${RELEASE_VENV_PY_VERSION}"
  echo "action=${RELEASE_VENV_ACTION}"
  echo "link=${dest}/.venv -> ${RELEASE_VENV_DIR}"
}

# ensure_release_venv <release-dir>: build or reuse, then link <release-dir>/.venv. Returns non-zero on any
# failure; the caller dies. Idempotent: an unchanged lock + interpreter reuses the venv with no pip install.
ensure_release_venv() {
  local dest="$1"
  [[ -d "$dest" ]] || { _rv_fail "release dir missing: $dest"; return 1; }
  release_venv_resolve "$dest" || return 1
  local lock="${dest}/${RELEASE_VENV_LOCK_NAME}" vdir="$RELEASE_VENV_DIR" ver="$RELEASE_VENV_PY_VERSION"
  local link="${dest}/.venv"
  if [[ -e "$link" && ! -L "$link" ]]; then
    _rv_fail "${link} exists and is not a symlink; refusing to replace it"
    return 1
  fi
  mkdir -p "$RELEASE_VENVS_BASE" || { _rv_fail "cannot create $RELEASE_VENVS_BASE"; return 1; }
  # One builder at a time per base; a concurrent prepare waits rather than racing pip into one dir.
  local lockfd
  exec {lockfd}>"${RELEASE_VENVS_BASE}/.build.lock"
  if ! flock -w "${TRADEAI_RELEASE_VENV_LOCK_WAIT_S:-900}" "$lockfd"; then
    exec {lockfd}>&-
    _rv_fail "timed out waiting for ${RELEASE_VENVS_BASE}/.build.lock"
    return 1
  fi
  local rc=0
  release_venv_resolve "$dest" || rc=$?   # re-read under the lock: another prepare may have just built it
  if [[ "$rc" -eq 0 ]]; then
    case "$RELEASE_VENV_ACTION" in
      reuse)
        _rv_log "release venv: reuse ${RELEASE_VENV_ID} (no rebuild)"
        _rv_verify "$vdir" "$lock" "$ver" || rc=$?
        ;;
      rebuild_incomplete)
        _rv_log "release venv: ${vdir} has no .complete (interrupted build, never linked) — rebuilding"
        rm -rf -- "$vdir"
        _rv_build "$vdir" "$lock" "$ver" || rc=$?
        ;;
      build)
        _rv_build "$vdir" "$lock" "$ver" || rc=$?
        ;;
    esac
  fi
  exec {lockfd}>&-
  [[ "$rc" -eq 0 ]] || return "$rc"
  ln -sfn -- "$vdir" "$link" || { _rv_fail "cannot link $link"; return 1; }
  [[ "$(readlink -- "$link")" == "$vdir" ]] || { _rv_fail "$link does not point at $vdir"; return 1; }
  RELEASE_VENV_PYTHON="${link}/bin/python"
  [[ -x "$RELEASE_VENV_PYTHON" ]] || { _rv_fail "$RELEASE_VENV_PYTHON not executable"; return 1; }
  export RELEASE_VENV_PYTHON
  _rv_log "release venv: ${link} -> ${vdir} (RELEASE_VENV_PYTHON=${RELEASE_VENV_PYTHON})"
}
