"""The scripts.lib bootstrap, and the guard on what it costs.

Both morning briefs were undelivered from 2026-08-28 because a cron line that
runs a script BY PATH gets sys.path[0] = <root>/scripts, so `import
scripts.lib.X` raised ModuleNotFoundError. The failure reproduced from the
SERVED release, so it was never a stale-checkout problem.

These tests run a real subprocess by path. Importing in-process would prove
nothing: pytest already has the root on sys.path, which is the exact mistake
that masked this failure once already.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_by_path(source: str, tmp_path: Path) -> subprocess.CompletedProcess:
    """Run a script the way cron does: by path, with a neutral cwd."""
    probe = ROOT / "scripts" / f"_pytest_probe_{tmp_path.name}.py"
    probe.write_text(source, encoding="utf-8")
    try:
        return subprocess.run(
            [sys.executable, str(probe)],
            cwd=str(tmp_path),  # never the repo root -- cwd must not rescue it
            capture_output=True,
            text=True,
            timeout=120,
        )
    finally:
        probe.unlink(missing_ok=True)


def test_a_bare_scripts_import_still_fails_by_path(tmp_path):
    """The bootstrap's honest limit, pinned so nobody assumes more than it does.

    `import scripts.lib.X` as the FIRST import cannot be rescued by this file:
    the bootstrap lives inside scripts/lib/__init__.py, which Python can only
    execute once `scripts` already resolves. Chicken-and-egg.

    The fix works because the real failing chain enters through the `lib.X`
    spelling, which IS importable when sys.path[0] is <root>/scripts. A future
    entrypoint written with the bare spelling will still fail, and should --
    loudly and immediately, not subtly.
    """
    r = _run_by_path(
        "import scripts.lib.cio_lineage_health\nprint('IMPORT_OK')\n", tmp_path
    )
    assert r.returncode == 1
    assert "No module named 'scripts'" in r.stderr


def test_sys_path_zero_is_scripts_not_root(tmp_path):
    """Pins WHY the bug existed, so a future reader does not have to rediscover it."""
    r = _run_by_path("import sys\nprint(sys.path[0])\n", tmp_path)
    assert r.returncode == 0
    assert r.stdout.strip().endswith("/scripts")


def test_the_bootstrap_is_what_fixes_it(tmp_path):
    """Mutation guard: without the root insert, the import must FAIL.

    Otherwise this file asserts a property something else already provides, and
    would keep passing if the bootstrap were deleted.
    """
    r = _run_by_path(
        "import sys\n"
        "from pathlib import Path\n"
        "_root = str(Path(__file__).resolve().parents[1])\n"
        "sys.path = [p for p in sys.path if p != _root]\n"
        "import importlib\n"
        "for m in [k for k in sys.modules if k == 'scripts' or k.startswith('scripts.')]:\n"
        "    del sys.modules[m]\n"
        "try:\n"
        "    importlib.import_module('scripts.lib.cio_lineage_health')\n"
        "    print('UNEXPECTEDLY_OK')\n"
        "except ModuleNotFoundError as e:\n"
        "    print('EXPECTED_FAILURE', e)\n",
        tmp_path,
    )
    assert r.returncode == 0, f"stderr={r.stderr!r}"
    assert "EXPECTED_FAILURE" in r.stdout, r.stdout


def test_dual_import_identity_raises():
    """The declared cost of the fix must fail loudly, not silently."""
    from scripts.lib import DualImportIdentityError, assert_single_import_identity

    assert_single_import_identity()  # clean state: no raise

    real = sys.modules["scripts.lib.cio_lineage_health"] = __import__(
        "scripts.lib.cio_lineage_health", fromlist=["x"]
    )
    sys.modules["lib.cio_lineage_health"] = type(sys)("lib.cio_lineage_health")
    try:
        with pytest.raises(DualImportIdentityError) as e:
            assert_single_import_identity()
        assert "cio_lineage_health" in str(e.value)
        assert real is not None
    finally:
        sys.modules.pop("lib.cio_lineage_health", None)

    assert_single_import_identity()  # restored


def test_the_real_delivery_chain_imports(tmp_path):
    """The actual regression, in the spelling the failing script uses.

    aegis_morning_brief_delivery.py:615 does `from lib.cio_operator_renderers
    import deliver_morning`, and inside that chain sits `from
    scripts.lib.brief_semantic_dedupe import ...` -- the import that raised
    ModuleNotFoundError from the SERVED release and left both morning briefs
    undelivered from 2026-08-28.

    Import only. This module delivers to the operator's phone; nothing here
    calls deliver_morning.
    """
    r = _run_by_path(
        "from lib.cio_operator_renderers import deliver_morning\nprint('CHAIN_OK')\n",
        tmp_path,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "CHAIN_OK" in r.stdout
