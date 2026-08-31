"""The researcher subprocess must launch with an interpreter that exists.

`research_scheduler.py` computed `PY = ROOT/".venv"/"bin"/"python"`, where ROOT
is the RELEASE directory. Releases stopped shipping a `.venv` between 9d92b6e0
and 1306132c, so that path exists in no release and every dispatch died at
`subprocess.run` with FileNotFoundError -- 19 of 19 on 2026-08-31, while the run
reported "19 external calls".

The monitor keys `attempts_24h` on rows written by the child, so a child that
never starts is indistinguishable from a lane nobody called. That is why the
deepseek lane read `attempts_24h=0` for nine days.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def _module():
    import importlib
    return importlib.import_module("research_scheduler")


def test_the_child_interpreter_exists():
    """The regression. A PY that does not exist is a lane that silently never runs."""
    mod = _module()
    assert Path(mod.PY).exists(), f"child interpreter does not exist: {mod.PY}"


def test_the_child_interpreter_can_actually_launch():
    """Existence is not enough -- prove it runs. Exit code checked for 0 exactly."""
    mod = _module()
    r = subprocess.run([mod.PY, "-c", "print('ok')"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr!r}"
    assert r.stdout.strip() == "ok"


def test_the_old_release_relative_expression_would_have_failed():
    """Guard the guard: prove the assertion can detect the defect it exists for.

    Without this, the tests above would pass against any interpreter at all and
    would not demonstrate that the release-relative path was the problem.
    """
    mod = _module()
    stale = Path(mod.ROOT) / ".venv" / "bin" / "python"
    if stale.exists():
        # A tree that does bundle a venv -- the defect cannot be reproduced here,
        # and saying so is better than asserting something untrue.
        pytest.skip(f"this tree bundles a venv at {stale}; defect not reproducible")
    with pytest.raises(FileNotFoundError):
        subprocess.run([str(stale), "-c", "pass"], capture_output=True, timeout=20)


def test_py_is_not_hardcoded_release_relative():
    src = (ROOT / "scripts" / "research_scheduler.py").read_text(encoding="utf-8")
    assert 'PY = str(ROOT / ".venv" / "bin" / "python")' not in src, \
        "the release-relative interpreter path is back"

