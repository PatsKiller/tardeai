"""A CI unit in which no test ran must fail (CIO-hardening alignment audit C2/M8, 2026-10-21).

Before: ``_unit_passed`` accepted pytest exit 0 or exit 5 with " skipped" in the output, so
main push run 39660558060 reported ``[PASS] telegram_notification_normalization (2 files)
2 skipped``; a deleted registered test file was filtered out of every plan; and a mandatory
gate named in config/ci_risk_tiers.json but absent from GATES only printed a warning.

After: each of those fails, except units whose every file is declared, with a reason, in
config/ci_skip_tolerant_units.json. Hermetic: synthetic outputs, tmp_path gate trees, no DB.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "run_cio_hardening_ci_skipgate", ROOT / "scripts" / "run_cio_hardening_ci.py"
)
ci = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ci)

A, B = "tests/test_a.py", "tests/test_b.py"


# ----------------------------------------------------------------------------- _unit_passed


@pytest.mark.parametrize(
    "rc,out",
    [
        (0, "...\n3 passed in 0.10s\n"),
        (0, "..s\n2 passed, 1 skipped in 0.10s\n"),
        (0, "x\n1 xfailed in 0.10s\n"),
        (0, "30 passed, 211 skipped, 2 warnings in 1.33s"),
    ],
)
def test_a_unit_where_a_test_ran_passes(rc, out):
    assert ci._unit_passed(rc, out, [A], {}) is True


@pytest.mark.parametrize(
    "rc,out",
    [
        (0, "ss\n2 skipped in 0.74s\n"),  # the measured telegram unit
        (5, "s\n1 skipped in 0.60s\n"),  # every module skipped at import
        (5, "\nno tests ran in 0.01s\n"),  # nothing collected
        (0, ""),  # no summary at all: no evidence a test ran
    ],
)
def test_a_unit_where_no_test_ran_fails(rc, out):
    assert ci._unit_passed(rc, out, [A, B], {}) is False


def test_skip_tolerance_needs_every_file_listed():
    out = "ss\n2 skipped in 0.74s\n"
    assert ci._unit_passed(0, out, [A, B], {A: "pg only", B: "pg only"}) is True
    assert ci._unit_passed(5, "no tests ran in 0.01s", [A], {A: "pg only"}) is True
    assert ci._unit_passed(0, out, [A, B], {A: "pg only"}) is False
    assert ci._unit_passed(0, out, [], {A: "pg only"}) is False


@pytest.mark.parametrize("rc", [1, 2, 3, 4])
def test_failures_and_collection_errors_never_pass_even_when_tolerant(rc):
    assert ci._unit_passed(rc, "1 failed in 0.1s", [A], {A: "pg only"}) is False


def test_summary_counts_are_parsed_from_the_last_summary_line():
    out = "noise 9 passed earlier\n..F\n=== 2 passed, 1 failed, 3 skipped, 1 error in 0.50s ===\n"
    assert ci.pytest_outcome_counts(out) == {"passed": 2, "failed": 1, "skipped": 3, "errors": 1}
    assert ci.pytest_outcome_counts("no summary here") is None


# ----------------------------------------------------------------------------- the reviewed list


def test_skip_tolerant_list_requires_a_reason_per_entry(tmp_path):
    p = tmp_path / "t.json"
    p.write_text(json.dumps({"schema": "CiSkipTolerantFiles@v1", "files": {A: {"reason": "  "}}}))
    with pytest.raises(ci.SkipTolerantConfigError):
        ci.load_skip_tolerant(p)
    p.write_text(json.dumps({"schema": "CiSkipTolerantFiles@v1", "files": {A: "pg only"}}))
    with pytest.raises(ci.SkipTolerantConfigError):
        ci.load_skip_tolerant(p)
    p.write_text(json.dumps({"schema": "other", "files": {}}))
    with pytest.raises(ci.SkipTolerantConfigError):
        ci.load_skip_tolerant(p)
    p.write_text(json.dumps({"schema": "CiSkipTolerantFiles@v1", "files": {A: {"reason": "pg only"}}}))
    assert ci.load_skip_tolerant(p) == {A: "pg only"}


def test_committed_skip_tolerant_list_is_small_reasoned_and_registered():
    tolerant = ci.load_skip_tolerant()
    registered = {p for _n, ps in ci.GATES for p in ps}
    assert 0 < len(tolerant) <= 10, "the list is an exception, not a bypass"
    for f, reason in tolerant.items():
        assert (ROOT / f).is_file(), f
        assert f in registered, f
        assert len(reason) >= 40, f


def test_measured_telegram_db_unit_is_tolerated_and_its_gate_is_not():
    tolerant = ci.load_skip_tolerant()
    db = ["tests/test_alert_occurrence_persistence_db.py", "tests/test_alert_delivery_recording_db.py"]
    assert ci._unit_passed(0, "ss\n2 skipped in 0.74s\n", db, tolerant) is True
    gate = dict(ci.GATES)["telegram_notification_normalization"]
    assert not all(f in tolerant for f in gate)


# ----------------------------------------------------------------------------- run_gates end to end


def _tree(tmp_path: Path, monkeypatch, files: dict[str, str], tolerant: dict[str, str] | None = None) -> None:
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    cfg = tmp_path / "skip_tolerant.json"
    cfg.write_text(
        json.dumps(
            {"schema": "CiSkipTolerantFiles@v1", "files": {f: {"reason": r} for f, r in (tolerant or {}).items()}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ci, "REPO", tmp_path)
    monkeypatch.setattr(ci, "SKIP_TOLERANT_PATH", cfg)


PASSING = "def test_ok():\n    assert True\n"
SKIPPING = "import pytest\npytest.importorskip('no_such_module_ci_20261021')\n\ndef test_x():\n    pass\n"
EMPTY = "X = 1\n"


@pytest.mark.parametrize("profile,jobs", [("fast", 2), ("full", 1)])
def test_run_gates_fails_an_all_skipped_unit_and_passes_a_real_one(tmp_path, monkeypatch, profile, jobs):
    _tree(
        tmp_path, monkeypatch, {"tests/test_ok.py": PASSING, "tests/test_skip.py": SKIPPING, "tests/test_e.py": EMPTY}
    )
    gates = [("ok", ["tests/test_ok.py"]), ("skip", ["tests/test_skip.py"]), ("empty", ["tests/test_e.py"])]
    assert ci.run_gates(gates, profile=profile, jobs=jobs) == ["skip", "empty"]


@pytest.mark.parametrize("profile,jobs", [("fast", 2), ("full", 1)])
def test_run_gates_accepts_a_declared_skip_tolerant_unit(tmp_path, monkeypatch, profile, jobs):
    _tree(tmp_path, monkeypatch, {"tests/test_skip.py": SKIPPING}, {"tests/test_skip.py": "needs a module CI lacks"})
    assert ci.run_gates([("skip", ["tests/test_skip.py"])], profile=profile, jobs=jobs) == []


@pytest.mark.parametrize("profile,jobs", [("fast", 2), ("full", 1)])
def test_run_gates_fails_a_gate_whose_registered_file_is_missing(tmp_path, monkeypatch, profile, jobs):
    _tree(tmp_path, monkeypatch, {"tests/test_ok.py": PASSING})
    gates = [
        ("ok", ["tests/test_ok.py"]),
        ("gone", ["tests/test_ok.py", "tests/test_deleted.py"]),
        ("all_gone", ["tests/test_x.py"]),
    ]
    assert ci.run_gates(gates, profile=profile, jobs=jobs) == ["gone", "all_gone"]
    assert ci.missing_registered_files(gates) == [("gone", "tests/test_deleted.py"), ("all_gone", "tests/test_x.py")]


def test_no_registered_file_is_missing_today():
    assert ci.missing_registered_files(ci.GATES) == []


# ----------------------------------------------------------------------------- unknown mandatory gates


def _fake_select(monkeypatch, tiers):
    sys.path.insert(0, str(ROOT))
    from scripts.lib import test_impact

    monkeypatch.setattr(test_impact, "load_map", lambda root: ({"rdeps": {}}, "cache"))
    monkeypatch.setattr(test_impact, "load_tiers", lambda: tiers)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.delenv("CIO_CI_SELECTION_OUT", raising=False)
    # main() chdirs and setdefaults env vars: make both revert after the test.
    monkeypatch.chdir(ROOT)
    for k, default in (("TRADE_AI_CI", "1"), ("CIO_TELEGRAM_INTERDICT", "1"), ("PYTEST_ADDOPTS", "")):
        monkeypatch.setenv(k, os.environ.get(k, default))


def test_unknown_mandatory_gate_fails_the_pr_selection(monkeypatch, capsys):
    name = ci.GATES[0][0]
    _fake_select(monkeypatch, {"smoke_gates": [name, "no_such_gate_20261021"], "high": {}, "low": {"globs": []}})
    with pytest.raises(ci.UnknownMandatoryGatesError) as exc:
        ci.select_pr_gates("origin/main", changed=["scripts/x.py"])
    assert exc.value.names == ["no_such_gate_20261021"]
    assert ci.main(["--profile", "pr", "--changed", "scripts/x.py", "--print-selection"]) == 1
    assert "risk_tiers_unknown_gates" in capsys.readouterr().out


def test_known_mandatory_gates_select_normally(monkeypatch):
    name = ci.GATES[0][0]
    _fake_select(monkeypatch, {"smoke_gates": [name], "high": {}, "low": {"globs": []}})
    gates, profile = ci.select_pr_gates("origin/main", changed=["scripts/x.py"])
    assert profile == "fast" and [n for n, _f in gates] == [name]
