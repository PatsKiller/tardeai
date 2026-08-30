"""Every test file is run by CI, or named and explained.

Measured 2026-08-30: the repository holds 1,009 test files and the hardening
runner's allowlist names 49 of them. **Every green CI run has reported on 4.9%
of the suite** and said nothing about the other 95%.

Why a coverage gate and not a switch to discovery: the unlisted suite does not
pass, and six files cannot be imported at all — one of them raises SystemExit at
module scope, which aborts the entire pytest run with INTERNALERROR rather than
failing one file. Flipping CI to discovery would turn it red on work unrelated
to whatever change triggered it, and a red gate nobody can green gets disabled,
which is how the 95% became invisible to begin with.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts/check_test_coverage.py"


def _gate():
    spec = importlib.util.spec_from_file_location("cov_gate", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_gate_is_green_on_this_tree():
    assert _gate().audit()["unlisted_new"] == []


def test_it_fails_on_a_new_unlisted_test_file():
    """A gate that can only pass is not a gate. Exit status read directly."""
    probe = ROOT / "tests/test_zz_coverage_gate_probe_tmp.py"
    probe.write_text("def test_probe():\n    assert True\n", encoding="utf-8")
    try:
        r = subprocess.run([sys.executable, str(GATE), "--fail-on-new"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=300)
        assert r.returncode == 1, r.stdout[-800:]
    finally:
        probe.unlink()
    r = subprocess.run([sys.executable, str(GATE), "--fail-on-new"],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=300)
    assert r.returncode == 0


def test_the_baseline_may_shrink_but_not_grow():
    """Adding a name to the baseline hides a file; the deny-list is where an
    exclusion goes, and it requires a reason."""
    src = GATE.read_text(encoding="utf-8")
    assert "UNLISTED_BASELINE" in src
    assert "must not grow" in src


def test_every_denied_file_carries_a_reason():
    g = _gate()
    assert g.DENY, "an empty deny-list would silently pass collection errors"
    for path, reason in g.DENY.items():
        assert reason.strip(), f"{path} is denied without a reason"


def test_the_reported_coverage_is_computed_not_asserted():
    """The percentage must come from counting, so it moves when the gates do."""
    r = _gate().audit()
    assert r["coverage_pct"] == round(100.0 * r["run_by_ci"] / max(r["test_files"], 1), 1)
    assert r["test_files"] > r["run_by_ci"], "this gate exists because they differ"
