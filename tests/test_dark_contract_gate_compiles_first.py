"""The dark-contract gate must fail on a module that does not compile.

Mutation-tested against the real defect on 2026-08-30. Commit aa21559c added a
module-level `NO_CONSUMER_REASON` ABOVE `from __future__ import annotations` in
scripts/cio_event_lifecycle_census.py to satisfy check_dark_contracts.py. That
placement is a SyntaxError. The file was unimportable for 10 hours while its
numbers were quoted, and the gate reported green the whole time, because
`ast.parse()` accepts a misplaced `__future__` import and `compile()` does not.

Measured before the fix:
    check_dark_contracts.py --fail-on-new  ->  exit 0   (output identical to clean)
Measured after:
    check_dark_contracts.py --fail-on-new  ->  exit 1   (names file + reason)

These tests plant that exact shape and require the gate to refuse it.
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts" / "check_dark_contracts.py"
PROBE = ROOT / "scripts" / "lib" / "_compile_gate_probe_tmp.py"

# A module-level assignment, then a __future__ import: legal to ast.parse,
# rejected by compile(). This is the outage verbatim.
BROKEN = (
    'NO_CONSUMER_REASON = "probe: hoisted above __future__"\n'
    '"""Probe module."""\n'
    "from __future__ import annotations\n"
    "\n"
    'SCHEMA = "CompileGateProbe@v1"\n'
)


def _load_gate():
    spec = importlib.util.spec_from_file_location("check_dark_contracts", GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def probe():
    PROBE.write_text(BROKEN, encoding="utf-8")
    try:
        yield PROBE
    finally:
        PROBE.unlink(missing_ok=True)


def test_the_probe_really_is_the_outage_shape():
    """Guard the guard: if this stops being a SyntaxError the test is vacuous."""
    ast.parse(BROKEN)  # must NOT raise -- this is why ast.parse was unsound
    with pytest.raises(SyntaxError) as exc:
        compile(BROKEN.encode("utf-8"), "probe", "exec")
    assert "__future__" in str(exc.value)


def test_module_compiles_uses_compile_not_ast_parse(probe):
    gate = _load_gate()
    ok, why = gate.module_compiles(str(probe.relative_to(ROOT)))
    assert ok is False
    assert "__future__" in why


def test_gate_exits_nonzero_on_an_uncompilable_module(probe):
    proc = subprocess.run(
        [sys.executable, str(GATE), "--fail-on-new"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 1, (
        "the dark-contract gate passed a module that cannot compile -- "
        f"exit={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    )
    combined = proc.stdout + proc.stderr
    assert "_compile_gate_probe_tmp.py" in combined, combined
    assert "uncompilable" in combined.lower(), combined


def test_gate_is_green_without_the_probe():
    """No false positive: the clean tree must still pass."""
    proc = subprocess.run(
        [sys.executable, str(GATE), "--fail-on-new"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "uncompilable modules      : 0" in proc.stdout
