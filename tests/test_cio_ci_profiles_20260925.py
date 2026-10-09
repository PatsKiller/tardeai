"""run_cio_hardening_ci profiles: the fast plan runs EVERY registered test exactly once.

2026-10-09 (CI design audit Q4/Q8): a file registered in several gates now runs once
per invocation (every gate still reports), and the serial tail is an explicit,
evidence-checked list instead of a regex over test source text.

2026-09-25 (operator: "speed up to like 5 mins"). Speed came from running gates in
a worker pool, never from dropping tests. These tests hold that line.
"""

from __future__ import annotations

import collections
import importlib.util
import re
from pathlib import Path

import pytest

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


def test_fast_plan_covers_every_registered_file_exactly_once():
    parallel, serial = ci.plan_units(ci.GATES)
    planned = collections.Counter()
    for _name, files in parallel + serial:
        planned.update(files)
    assert set(planned) == set(_registered_files())
    assert set(planned.values()) == {1}


def test_fast_plan_drops_no_gate():
    parallel, serial = ci.plan_units(ci.GATES)
    _deduped, also_in = ci.dedupe_gates(ci.GATES)
    planned = {name for name, _ in parallel + serial} | set(also_in)
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
    assert set(planned) == set(_registered_files())
    assert set(planned.values()) == {1}


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


def test_gate_needs_serial_reads_the_explicit_list_not_source_text(tmp_path, monkeypatch):
    monkeypatch.setattr(ci, "REPO", tmp_path)
    monkeypatch.setattr(ci, "SERIAL_FILES", {"tests/a.py": "x"})
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a.py").write_text("def test(tmp_path): pass\n", encoding="utf-8")
    # source text that the pre-2026-10-09 regex matched; it is NOT shared state by itself
    (tmp_path / "tests" / "b.py").write_text('def test(m2_conn): assert "docs/INDEX.md"\n', encoding="utf-8")
    assert ci.gate_needs_serial("x", ["tests/a.py"]) is True
    assert ci.gate_needs_serial("x", ["tests/b.py"]) is False


# ── Q8: the serial list is exactly the verified shared-state files ───────────────

#: Verified by reading each test (2026-10-09). Changing the serial tail means changing
#: this set AND ci.SERIAL_FILES, with the evidence line, in the same review.
VERIFIED_SERIAL = {
    "tests/test_overnight_g3_docs_index.py",  # rewrites the committed docs/INDEX.md
    "tests/test_goal_work_minter_ratchet.py",  # plants a probe into scripts/
    "tests/test_provider_chokepoint_ratchet.py",  # plants a probe into scripts/
    "tests/test_scripts_lib_bootstrap.py",  # plants a probe into scripts/
    "tests/test_overnight_g2_import_normalise.py",  # plants a probe into scripts/
    "tests/test_detectors_distinguish_states.py",  # plants a probe under docs/_design/
    "tests/test_bitemporal_correctness.py",  # schema DDL on the one shared M2 test DB
    "tests/test_memory_prod_cutover_20260924.py",  # schema DDL on the one shared M2 test DB
}


def test_serial_list_matches_the_verified_set():
    assert set(ci.SERIAL_FILES) == VERIFIED_SERIAL
    _parallel, serial = ci.plan_units(ci.GATES)
    assert {f for _n, files in serial for f in files} == VERIFIED_SERIAL


def test_each_serial_entry_is_registered_and_still_does_what_it_is_listed_for():
    registered = set(_registered_files())
    for path, evidence in ci.SERIAL_FILES.items():
        assert path in registered, path
        # A test made hermetic loses its evidence line -> it must leave the serial list.
        assert evidence in (ROOT / path).read_text(encoding="utf-8"), (path, evidence)


# A registered test that writes into the real checkout but is not on the list would run
# concurrently with tree scans. The planting shapes this repo uses:
_PLANT_RE = re.compile(
    r"""\b(?:ROOT|REPO)\s*/\s*["']scripts["']\s*/\s*f?["']_"""  # a probe file named _... under scripts/
    r"""|\b(?:ROOT|REPO)\s*/\s*["']docs["']\s*/\s*["']INDEX\.md["']"""  # the committed docs index
    r"""|["']_design["']\s*/\s*["']__pytest_probe__["']"""  # docs/_design probe
)


def test_no_unlisted_registered_test_plants_into_the_checkout():
    offenders = sorted(
        p for p in _registered_files()
        if p not in ci.SERIAL_FILES and _PLANT_RE.search((ROOT / p).read_text(encoding="utf-8", errors="replace"))
    )
    assert offenders == [], f"add to SERIAL_FILES (with evidence) or make hermetic: {offenders}"


def test_regex_false_positives_now_run_in_the_pool():
    parallel, _serial = ci.plan_units(ci.GATES)
    parallel_files = {f for _n, files in parallel for f in files}
    for p in (
        "tests/test_alarm_fires_scalp_alerts_20261005.py",  # "docs/INDEX.md" inside an assert
        "tests/test_guard_push_auth.py",  # git commit inside a tmp_path repo
        "tests/test_agent_worktree_identity.py",  # git worktree inside a tmp_path repo
        "tests/test_telegram_chokepoint_ratchet.py",  # probe planted under tmp_path
        "tests/test_alert_delivery_recording_db.py",  # its own isolated DSN, skips without one
    ):
        if (ROOT / p).is_file():
            assert p in parallel_files, p


# ── Q4: a file registered in several gates runs once; every gate still reports ───

def _fake_repo(tmp_path, monkeypatch, names):
    monkeypatch.setattr(ci, "REPO", tmp_path)
    monkeypatch.setattr(ci, "SERIAL_FILES", {})
    (tmp_path / "tests").mkdir()
    for n in names:
        (tmp_path / "tests" / n).write_text("def test_x(): pass\n", encoding="utf-8")


def test_dedupe_keeps_first_registration_and_records_the_others(tmp_path, monkeypatch):
    _fake_repo(tmp_path, monkeypatch, ["a.py", "b.py", "c.py"])
    gates = [
        ("g1", ["tests/a.py", "tests/b.py"]),
        ("g2", ["tests/b.py", "tests/c.py", "tests/missing.py"]),
        ("g3", ["tests/a.py"]),
    ]
    deduped, also_in = ci.dedupe_gates(gates)
    assert deduped == [("g1", ["tests/a.py", "tests/b.py"]), ("g2", ["tests/c.py"]), ("g3", [])]
    assert also_in == {"g2": [("tests/b.py", "g1")], "g3": [("tests/a.py", "g1")]}
    parallel, serial = ci.plan_units(gates, hints={})
    planned = collections.Counter(f for _n, fs in parallel + serial for f in fs)
    assert planned == collections.Counter(["tests/a.py", "tests/b.py", "tests/c.py"])


def test_registered_duplicates_exist_and_are_folded():
    _deduped, also_in = ci.dedupe_gates(ci.GATES)
    folded = sum(len(v) for v in also_in.values())
    total = sum(_registered_files().values())
    assert folded == total - len(_registered_files())


@pytest.mark.parametrize("fail_file,expect_failed", [
    (None, []),
    ("tests/b.py", ["g1", "g2"]),  # the shared file's unit failed: both registrants fail
    ("tests/c.py", ["g2"]),
    ("tests/a.py", ["g1", "g3"]),  # g3 has no unit of its own and still reports the failure
])
def test_shared_file_result_is_reported_under_every_gate(tmp_path, monkeypatch, capsys, fail_file, expect_failed):
    _fake_repo(tmp_path, monkeypatch, ["a.py", "b.py", "c.py"])
    gates = [("g1", ["tests/a.py", "tests/b.py"]), ("g2", ["tests/b.py", "tests/c.py"]), ("g3", ["tests/a.py"])]
    monkeypatch.setattr(ci, "load_duration_hints", lambda *a, **k: {"tests/a.py": 30.0, "tests/b.py": 30.0})
    runs = []

    def fake_unit(unit):
        name, files = unit
        runs.extend(files)
        rc = 1 if fail_file in files else 0
        return name, files, rc, "1 passed" if rc == 0 else "1 failed", 0.1

    monkeypatch.setattr(ci, "_run_unit", fake_unit)
    failed = ci.run_gates(gates, profile="fast", jobs=2)
    assert sorted(failed) == expect_failed
    assert sorted(runs) == ["tests/a.py", "tests/b.py", "tests/c.py"]  # each file once
    out = capsys.readouterr().out
    assert "] g3 (also 1 files run once under g1)" in out


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
