"""The scalp shadow wrapper must run the tree it was invoked from, and must forward a mode flag.

Two cutover requirements the wrapper did not meet:

* `PROJ` was the canonical checkout's absolute path, so an n8n run (cwd = code root) would still execute the
  canonical tree — the cutover would be a no-op that looks like a success. It now resolves from the script's own
  location, which is identical for the live cron line (the script lives in the canonical tree).
* The wrapper hardcoded `--live --apply --top 0`, so there was no dry-run arm at all even though
  scripts/scalp_shadow_logger.py has `--dry-run`. Extra argv is now forwarded to the Python.

The test runs a copy of the wrapper against stub `python`/`safe_flock.sh` inside a temporary tree, so it proves
the wrapper's own behaviour and touches nothing live.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "scripts" / "run_scalp_shadow_logger.sh"

_STUB_PYTHON = """#!/usr/bin/env bash
# stub interpreter: answer the holdings -c probe, otherwise record the argv the wrapper produced
if [ "${1:-}" = "-c" ]; then echo 1000; exit 0; fi
printf '%s\\n' "$@" >> "$ARGV_LOG"
"""

_STUB_SAFE_FLOCK = """#!/usr/bin/env bash
# stub safe_flock.sh: <lock> <cmd...> -> exec the command
shift
exec "$@"
"""


def _tree(tmp_path: Path) -> Path:
    tree = tmp_path / "tree"
    (tree / "scripts").mkdir(parents=True)
    (tree / ".venv" / "bin").mkdir(parents=True)
    (tree / "data" / "portfolios" / "state").mkdir(parents=True)
    shutil.copy2(WRAPPER, tree / "scripts" / "run_scalp_shadow_logger.sh")
    (tree / ".venv" / "bin" / "python").write_text(_STUB_PYTHON)
    (tree / "scripts" / "safe_flock.sh").write_text(_STUB_SAFE_FLOCK)
    (tree / "data" / "portfolios" / "state" / "holdings.json").write_text('{"portfolio_totals": {"total_value": 1000}}')
    for p in (tree / ".venv" / "bin" / "python", tree / "scripts" / "safe_flock.sh"):
        p.chmod(0o755)
    (tmp_path / "home").mkdir()
    return tree


def _run(tree: Path, tmp_path: Path, argv: list[str]) -> list[str]:
    log = tmp_path / "argv.log"
    env = dict(os.environ, HOME=str(tmp_path / "home"), ARGV_LOG=str(log))
    env.pop("SCALP_ENGINE_DISABLED", None)
    proc = subprocess.run(["bash", str(tree / "scripts" / "run_scalp_shadow_logger.sh"), *argv],
                          env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert log.exists(), "the stub interpreter never ran"
    return log.read_text().splitlines()


def test_the_wrapper_runs_the_python_in_the_tree_it_was_invoked_from(tmp_path):
    tree = _tree(tmp_path)
    argv = _run(tree, tmp_path, ["--dry-run"])
    # The recorded argv is exactly what the wrapper handed the interpreter; the wrapper's own cd decided which
    # interpreter exists — only the copied tree has one, so the run proves PROJ resolved to this tree.
    assert "--live" in argv and "--apply" in argv, argv


def test_the_wrapper_forwards_extra_argv_so_dry_run_reaches_the_python(tmp_path):
    tree = _tree(tmp_path)
    argv = _run(tree, tmp_path, ["--dry-run"])
    assert "--dry-run" in argv, f"the wrapper swallowed the dry-run flag: {argv}"


def test_no_argument_is_forwarded_when_the_cron_line_passes_none(tmp_path):
    """The live cron line passes no args, so its behaviour must be byte-identical to before the change."""
    tree = _tree(tmp_path)
    argv = _run(tree, tmp_path, [])
    assert argv == ["scripts/scalp_shadow_logger.py", "--live", "--apply", "--top", "0"], argv


def test_the_wrapper_no_longer_hardcodes_the_canonical_checkout():
    src = WRAPPER.read_text()
    # A literal absolute assignment is the defect; the value itself never belongs in a test (PII gate, and it is
    # environment-specific). Resolving PROJ from BASH_SOURCE is the fix under test.
    assert not re.search(r'^\s*PROJ="/', src, re.M), (
        "a hardcoded canonical path makes the n8n run execute the served tree while reporting success"
    )
    assert "BASH_SOURCE" in src
    assert '"$@"' in src
