"""Run-from-release P0: the shared, lock-hash-keyed release venv (2026-10-15).

Design: RUN_FROM_RELEASE.md §2 (arch-review-20261014). prepare builds or reuses
``<base>/py<X.Y.Z>-<sha12(requirements.lock.txt)>`` and links ``<release>/.venv`` to it.

Pinned here:
  * keying: the id is the pinned interpreter's version plus the lock hash; a new lock is a new dir and the
    old one is untouched;
  * reuse: an unchanged id runs no ``venv`` and no ``pip install`` again;
  * failure: a failed install or smoke import leaves no partial venv, no ``.venv`` link, and the previous
    venv untouched, and returns non-zero (prepare dies on it);
  * the link: ``<release>/.venv`` -> the venv, and ``RELEASE_VENV_PYTHON`` is exposed;
  * refusals: wrong interpreter minor, a venv whose freeze drifted from the lock, a real ``.venv`` dir;
  * the dry paths (``release_venv_plan`` and the deploy script's ``venv-plan``) write nothing;
  * prepare wiring: called after the overlay, fatal on failure, and ``VENV_PYTHON`` / units untouched.

Hermetic: a temp root and a stub interpreter whose ``-m venv`` / ``-m pip`` are shell; no network, no pip.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "scripts" / "lib" / "release_venv.sh"
DEPLOY = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"
LOCK = ROOT / "requirements.lock.txt"

COVERS = ["scripts/lib/release_venv.sh", "scripts/cio_phase2_exact_main_deploy.sh", "requirements.lock.txt"]

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("flock") and shutil.which("sha256sum")),
    reason="needs bash, flock, sha256sum",
)

# A stand-in interpreter. `-m venv D` makes D/bin/python (a copy of this stub); `-m pip install -r L`
# records L as the venv's frozen set; `-m pip freeze` prints it; `-c` answers the version probe or the
# smoke import. Every venv/pip call is appended to $STUB_LOG so tests can count rebuilds.
STUB = r"""#!/usr/bin/env bash
set -u
self_dir="$(cd "$(dirname "$0")" && pwd)"
log() { [[ -n "${STUB_LOG:-}" ]] && echo "$*" >>"$STUB_LOG"; return 0; }
if [[ "${1:-}" == "-c" ]]; then
  case "${2:-}" in
    *version_info*) echo "${STUB_VERSION:-3.14.4}"; exit 0 ;;
    import*) log "smoke"; [[ "${STUB_FAIL:-}" == "smoke" ]] && exit 1; exit 0 ;;
  esac
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
  d="$3"; log "venv $d"
  [[ "${STUB_FAIL:-}" == "venv" ]] && exit 1
  mkdir -p "$d/bin" && cp "$0" "$d/bin/python" && chmod +x "$d/bin/python"
  echo "home = $(dirname "$0")" >"$d/pyvenv.cfg"
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
  shift 2
  sub="$1"; shift
  if [[ "$sub" == "install" ]]; then
    lock=""
    while [[ $# -gt 0 ]]; do [[ "$1" == "-r" ]] && lock="$2"; shift; done
    log "pip_install $lock"
    mkdir -p "$self_dir/../lib/site-packages" && echo partial >"$self_dir/../lib/site-packages/half.py"
    [[ "${STUB_FAIL:-}" == "pip" ]] && exit 1
    cp "$lock" "$self_dir/../.frozen"
    exit 0
  fi
  if [[ "$sub" == "freeze" ]]; then
    log "pip_freeze"
    cat "$self_dir/../.frozen"
    exit 0
  fi
fi
exit 2
"""


@pytest.fixture
def env(tmp_path):
    stub_dir = tmp_path / "usr_bin"
    stub_dir.mkdir()
    py = stub_dir / "python3.14"
    py.write_text(STUB)
    py.chmod(0o755)
    base = tmp_path / "trade-ai-releases" / "venvs"
    log = tmp_path / "stub.log"
    e = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path / "home"),
        "TRADEAI_RELEASE_VENVS_BASE": str(base),
        "TRADEAI_RELEASE_PYTHON": str(py),
        "TRADEAI_RELEASE_PYTHON_MINOR": "3.14",
        "STUB_LOG": str(log),
    }
    return {"tmp": tmp_path, "base": base, "log": log, "env": e}


def _release(tmp: Path, name: str, lock_text: str) -> Path:
    rel = tmp / "trade-ai-releases" / "portfolio-server" / name
    rel.mkdir(parents=True)
    (rel / "requirements.lock.txt").write_text(lock_text)
    return rel


def _run(env: dict, fn: str, rel: Path, **extra) -> subprocess.CompletedProcess:
    e = dict(env["env"])
    e.update({k: str(v) for k, v in extra.items()})
    script = (
        f'set -euo pipefail; source "{LIB}"; {fn} "$1"; '
        'echo "RV_ID=$RELEASE_VENV_ID"; echo "RV_PY=$RELEASE_VENV_PYTHON"; echo "RV_ACTION=$RELEASE_VENV_ACTION"'
    )
    return subprocess.run(["bash", "-c", script, "_", str(rel)], env=e, capture_output=True, text=True)


def _out(cp: subprocess.CompletedProcess, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", cp.stdout, re.M)
    assert m, cp.stdout + cp.stderr
    return m.group(1)


def _calls(env: dict, kind: str) -> int:
    if not env["log"].exists():
        return 0
    return sum(1 for line in env["log"].read_text().splitlines() if line.startswith(kind))


LOCK_A = "pandas==3.0.1\nrequests==2.33.0\n"
LOCK_B = "pandas==3.0.2\nrequests==2.33.0\n"


def _expected_id(lock_text: str, ver: str = "3.14.4") -> str:
    return f"py{ver}-{hashlib.sha256(lock_text.encode()).hexdigest()[:12]}"


def test_id_is_interpreter_version_plus_lock_hash(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    cp = _run(env, "ensure_release_venv", rel)
    assert cp.returncode == 0, cp.stderr
    assert _out(cp, "RV_ID") == _expected_id(LOCK_A)
    vdir = env["base"] / _expected_id(LOCK_A)
    marker = (vdir / ".complete").read_text()
    assert f"lock_sha256={hashlib.sha256(LOCK_A.encode()).hexdigest()}" in marker
    assert "python_version=3.14.4" in marker


def test_symlink_and_exposed_python(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    cp = _run(env, "ensure_release_venv", rel)
    assert cp.returncode == 0, cp.stderr
    link = rel / ".venv"
    assert link.is_symlink()
    assert Path(os.readlink(link)) == env["base"] / _expected_id(LOCK_A)
    py = _out(cp, "RV_PY")
    assert py == f"{link}/bin/python"
    assert os.access(py, os.X_OK)


def test_unchanged_hash_reuses_without_rebuild(env):
    rel1 = _release(env["tmp"], "r1", LOCK_A)
    assert _run(env, "ensure_release_venv", rel1).returncode == 0
    vdir = env["base"] / _expected_id(LOCK_A)
    marker_before = (vdir / ".complete").read_text()
    assert (_calls(env, "venv"), _calls(env, "pip_install")) == (1, 1)

    rel2 = _release(env["tmp"], "r2", LOCK_A)
    cp = _run(env, "ensure_release_venv", rel2)
    assert cp.returncode == 0, cp.stderr
    assert _out(cp, "RV_ACTION") == "reuse"
    assert (_calls(env, "venv"), _calls(env, "pip_install")) == (1, 1)  # no rebuild
    assert (vdir / ".complete").read_text() == marker_before
    assert os.readlink(rel2 / ".venv") == os.readlink(rel1 / ".venv")
    # Idempotent on the same release too.
    assert _run(env, "ensure_release_venv", rel2).returncode == 0
    assert _calls(env, "pip_install") == 1


def test_new_lock_is_new_dir_old_untouched(env):
    rel1 = _release(env["tmp"], "r1", LOCK_A)
    assert _run(env, "ensure_release_venv", rel1).returncode == 0
    old = env["base"] / _expected_id(LOCK_A)
    old_marker = (old / ".complete").read_text()

    rel2 = _release(env["tmp"], "r2", LOCK_B)
    cp = _run(env, "ensure_release_venv", rel2)
    assert cp.returncode == 0, cp.stderr
    new = env["base"] / _expected_id(LOCK_B)
    assert new != old and (new / ".complete").is_file()
    assert (old / ".complete").read_text() == old_marker
    assert (old / ".frozen").read_text() == LOCK_A
    assert Path(os.readlink(rel1 / ".venv")) == old


@pytest.mark.parametrize("failure", ["pip", "smoke", "venv"])
def test_failed_build_leaves_no_partial_and_previous_untouched(env, failure):
    rel1 = _release(env["tmp"], "r1", LOCK_A)
    assert _run(env, "ensure_release_venv", rel1).returncode == 0
    old = env["base"] / _expected_id(LOCK_A)
    old_marker = (old / ".complete").read_text()

    rel2 = _release(env["tmp"], "r2", LOCK_B)
    cp = _run(env, "ensure_release_venv", rel2, STUB_FAIL=failure)
    assert cp.returncode != 0
    assert "release venv" in cp.stderr and "failed" in cp.stderr
    assert not (env["base"] / _expected_id(LOCK_B)).exists()  # no partial venv
    assert not (rel2 / ".venv").exists() and not (rel2 / ".venv").is_symlink()
    assert (old / ".complete").read_text() == old_marker  # previous venv untouched
    assert Path(os.readlink(rel1 / ".venv")) == old


def test_failed_build_then_success_builds_clean(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    assert _run(env, "ensure_release_venv", rel, STUB_FAIL="pip").returncode != 0
    cp = _run(env, "ensure_release_venv", rel)
    assert cp.returncode == 0, cp.stderr
    assert (env["base"] / _expected_id(LOCK_A) / ".complete").is_file()


def test_incomplete_dir_is_rebuilt_not_reused(env):
    vdir = env["base"] / _expected_id(LOCK_A)
    (vdir / "bin").mkdir(parents=True)  # an interrupted build: no .complete
    rel = _release(env["tmp"], "r1", LOCK_A)
    cp = _run(env, "ensure_release_venv", rel)
    assert cp.returncode == 0, cp.stderr
    assert _calls(env, "pip_install") == 1
    assert (vdir / ".complete").is_file()


def test_interpreter_minor_mismatch_refused(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    cp = _run(env, "ensure_release_venv", rel, STUB_VERSION="3.13.7")
    assert cp.returncode != 0
    assert "pinned minor is 3.14" in cp.stderr
    assert not env["base"].exists()
    assert not (rel / ".venv").is_symlink()


def test_freeze_drift_on_reuse_refused(env):
    rel1 = _release(env["tmp"], "r1", LOCK_A)
    assert _run(env, "ensure_release_venv", rel1).returncode == 0
    vdir = env["base"] / _expected_id(LOCK_A)
    (vdir / ".frozen").write_text(LOCK_A + "extra==1.0\n")  # someone ran pip install in the shared venv
    rel2 = _release(env["tmp"], "r2", LOCK_A)
    cp = _run(env, "ensure_release_venv", rel2)
    assert cp.returncode != 0
    assert "pip freeze != lock" in cp.stderr
    assert not (rel2 / ".venv").is_symlink()
    assert (vdir / ".frozen").read_text().endswith("extra==1.0\n")  # refused, never repaired


def test_real_venv_dir_in_release_refused(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    (rel / ".venv").mkdir()
    cp = _run(env, "ensure_release_venv", rel)
    assert cp.returncode != 0
    assert "not a symlink" in cp.stderr
    assert not env["base"].exists()


def test_missing_lock_refused(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    (rel / "requirements.lock.txt").unlink()
    cp = _run(env, "ensure_release_venv", rel)
    assert cp.returncode != 0
    assert "lock file missing" in cp.stderr


def test_plan_is_dry(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    cp = _run(env, "release_venv_plan", rel)
    assert cp.returncode == 0, cp.stderr
    assert "action=build" in cp.stdout
    assert f"venv_id={_expected_id(LOCK_A)}" in cp.stdout
    assert not env["base"].exists()
    assert not (rel / ".venv").is_symlink()
    assert _calls(env, "venv") == 0 and _calls(env, "pip") == 0
    assert _run(env, "ensure_release_venv", rel).returncode == 0
    assert "action=reuse" in _run(env, "release_venv_plan", rel).stdout


def test_deploy_venv_plan_subcommand_is_dry(env):
    rel = _release(env["tmp"], "r1", LOCK_A)
    cp = subprocess.run(["bash", str(DEPLOY), "venv-plan", str(rel)], env=env["env"], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    assert "action=build" in cp.stdout
    assert not env["base"].exists()
    assert not (rel / ".venv").is_symlink()


def _fn_body(src: str, name: str) -> str:
    m = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}", src, re.M | re.S)
    assert m, name
    return m.group(1)


def test_prepare_wiring():
    src = DEPLOY.read_text()
    body = _fn_body(src, "cmd_prepare")
    assert body.index("overlay_main") < body.index("ensure_release_venv")
    assert 'ensure_release_venv "$NEW_RELEASE" || die' in body
    assert '".venv/bin/python"' in body  # critical-path check when the venv is on
    # Prepare moves no cron line and no unit; VENV_PYTHON (ExecStart) keeps its dev-venv default.
    for forbidden in ("crontab", "systemctl", "write_systemd", "VENV_PYTHON="):
        assert forbidden not in body, forbidden
    assert 'VENV_PYTHON="${VENV_PYTHON:-${CANONICAL_SOURCE}/.venv/bin/python}"' in src
    lib = LIB.read_text()
    for forbidden in ("crontab", "systemctl"):
        assert not re.search(rf"^[^#]*\b{forbidden}\b", lib, re.M), forbidden


def test_committed_lock_is_a_full_pin_set():
    lines = [ln for ln in LOCK.read_text().splitlines() if ln.strip()]
    assert len(lines) >= 100
    assert all(re.fullmatch(r"[A-Za-z0-9_.\-]+==[A-Za-z0-9_.+!\-]+", ln) for ln in lines), [
        ln for ln in lines if "==" not in ln
    ]
    names = {ln.split("==")[0].lower().replace("_", "-") for ln in lines}
    assert {"pip", "psycopg2-binary", "pandas", "requests"} <= names
