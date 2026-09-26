"""run_cio_hardening_ci profiles: the fast plan runs EVERY registered test exactly once.

2026-09-25 (operator: "speed up to like 5 mins"). Speed came from running gates in
a worker pool, never from dropping tests. These tests hold that line.
"""

from __future__ import annotations

import collections
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_cio_hardening_ci", ROOT / "scripts" / "run_cio_hardening_ci.py")
ci = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(ci)


def _registered_files():
    out = collections.Counter()
    for _name, paths in ci.GATES:
        out.update(p for p in paths if (ROOT / p).is_file())
    return out


def test_fast_plan_covers_every_registered_file_exactly_as_often_as_registered():
    parallel, serial = ci.plan_units(ci.GATES)
    planned = collections.Counter()
    for _name, files in parallel + serial:
        planned.update(files)
    assert planned == _registered_files()


def test_fast_plan_drops_no_gate():
    parallel, serial = ci.plan_units(ci.GATES)
    planned = {name for name, _ in parallel + serial}
    declared = {name for name, paths in ci.GATES if any((ROOT / p).is_file() for p in paths)}
    assert planned == declared


def test_large_gates_are_packed_into_bounded_units():
    hints = ci.load_duration_hints()
    parallel, _serial = ci.plan_units(ci.GATES, unit_seconds=25, hints=hints)
    by_gate = collections.Counter(name for name, _ in parallel)
    assert by_gate.get("maturity_overnight_20260912", 0) > 1
    for _name, files in parallel:
        weight = sum(hints.get(p, ci.DEFAULT_FILE_SECONDS) for p in files)
        # a unit exceeds the target only when a single file does
        assert weight <= 25 or len(files) == 1, (files, weight)


def test_stale_or_missing_hints_never_drop_a_test():
    parallel, serial = ci.plan_units(ci.GATES, hints={})
    planned = collections.Counter()
    for _name, files in parallel + serial:
        planned.update(files)
    assert planned == _registered_files()


def test_shared_state_files_run_serially_and_the_rest_of_their_gate_does_not():
    parallel, serial = ci.plan_units(ci.GATES)
    serial_files = {f for _name, files in serial for f in files}
    # mutates the committed docs/INDEX.md to prove the drift gate goes red
    assert "tests/test_overnight_g3_docs_index.py" in serial_files
    # Postgres-backed memory suite (m2_conn fixture)
    assert "tests/test_bitemporal_correctness.py" in serial_files
    # ...while the rest of that gate stays parallel
    parallel_files = {f for _name, files in parallel for f in files}
    assert "tests/test_release_pin_and_validator.py" in parallel_files


def test_gate_needs_serial_detects_patterns(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "REPO", tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.py").write_text("def test(m2_conn): pass\n", encoding="utf-8")
    (tmp_path / "tests" / "b.py").write_text("def test(tmp_path): pass\n", encoding="utf-8")
    assert ci.gate_needs_serial("x", ["tests/a.py"]) is True
    assert ci.gate_needs_serial("x", ["tests/b.py"]) is False


def test_profile_and_jobs_defaults(monkeypatch):
    monkeypatch.delenv("CIO_CI_PROFILE", raising=False)
    assert ci._profile_from_env() == "fast"
    monkeypatch.setenv("CIO_CI_PROFILE", "full")
    assert ci._profile_from_env() == "full"
    monkeypatch.setenv("CIO_CI_JOBS", "3")
    assert ci._default_jobs() == 3


def test_ensure_test_database_refuses_the_live_shadow_and_foreign_names():
    spec_e = importlib.util.spec_from_file_location(
        "ensure_m2_test_database", ROOT / "scripts" / "ensure_m2_test_database.py"
    )
    ens = importlib.util.module_from_spec(spec_e)
    assert spec_e.loader is not None
    spec_e.loader.exec_module(ens)
    for bad in ("m2_shadow", "postgres", "m2_shadow_test;drop", "M2_SHADOW_TEST_X", "m2_shadow_testx"):
        assert ens.main(["--name", bad, "--dry-run"]) == 2, bad
