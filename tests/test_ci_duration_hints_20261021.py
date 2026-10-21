"""Shard duration hints stay measured and complete (alignment audit H5, 2026-10-21).

config/ci_shard_duration_hints.json was last refreshed 2026-10-10; 346 of 1,236 registered files
had no hint and were weighted at 1 s (one of them the 230-370 s trading-lock pair), so shard
balance and every estimate built on it were fiction. It is now refreshed from the
cio-shard-timings artifact of ci-gate run 39661659376, and this gate fails when more than 10% of
registered files lack a hint.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "run_cio_ci_hints_20261021", ROOT / "scripts" / "run_cio_hardening_ci.py"
)
ci = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ci)

DOC = json.loads(ci.SHARD_HINTS_PATH.read_text(encoding="utf-8"))


def test_at_most_ten_percent_of_registered_files_lack_a_shard_hint():
    missing, total = ci.hint_coverage(ci.GATES, ci.load_duration_hints(ci.SHARD_HINTS_PATH))
    assert total > 0
    frac = len(missing) / total
    assert frac <= ci.HINT_MISSING_MAX_FRACTION, (
        f"{len(missing)} of {total} registered test files ({frac:.1%}) have no entry in "
        f"config/ci_shard_duration_hints.json (limit {ci.HINT_MISSING_MAX_FRACTION:.0%}). Refresh it from the "
        f"cio-shard-timings artifact of the latest green ci-gate run. First missing: {missing[:10]}"
    )


def _gates(tmp_path, monkeypatch, n):
    for i in range(n):
        (tmp_path / "tests").mkdir(exist_ok=True)
        (tmp_path / "tests" / f"test_{i}.py").write_text("def test(): pass\n", encoding="utf-8")
    monkeypatch.setattr(ci, "REPO", tmp_path)
    return [("g", [f"tests/test_{i}.py" for i in range(n)] + ["tests/test_deleted.py"])]


@pytest.mark.parametrize("hinted,ok", [(20, True), (18, True), (17, False), (0, False)])
def test_hint_coverage_threshold(tmp_path, monkeypatch, hinted, ok):
    gates = _gates(tmp_path, monkeypatch, 20)
    hints = {f"tests/test_{i}.py": 1.5 for i in range(hinted)}
    missing, total = ci.hint_coverage(gates, hints)
    assert total == 20  # a missing file is not counted (the missing-file check owns that)
    assert len(missing) == 20 - hinted
    assert (len(missing) / total <= ci.HINT_MISSING_MAX_FRACTION) is ok


def test_hints_are_measured_from_a_named_run_and_sane():
    assert DOC["schema"] == "CiShardTimings@v1"
    assert DOC["source_run"] == 39661659376
    assert len(DOC["source_sha"]) == 40
    assert all(isinstance(v, (int, float)) and 0 <= v < 3600 for v in DOC["files"].values())
    # the longest measured unit on main is the trading-lock pair; a 1 s default would hide it
    assert DOC["files"]["tests/test_trading_lock_coverage_20261014.py"] >= 60


def test_shard_plan_uses_the_refreshed_hints():
    hints = ci.shard_hints()
    assert (
        hints["tests/test_trading_lock_coverage_20261014.py"]
        == DOC["files"]["tests/test_trading_lock_coverage_20261014.py"]
    )
