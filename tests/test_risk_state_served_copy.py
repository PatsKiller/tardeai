"""The risk producer must write where the CIO reads.

Measured 2026-08-28: portfolio_orchestrator runs `cd $PROJ` on cron 15 7 * * 1-5
and resolves state_dir from its own project_root (portfolio_orchestrator.py:116),
so the fresh file landed in the checkout while the CIO snapshot read
persistent-state.

    checkout          08-28 07:30   stop_count 26   total_unprotected_mv 650,158.77
    persistent-state  08-26 07:31   stop_count 25   total_unprotected_mv 476,057.12

A $174k difference in unprotected market value, on a money surface, for two days.

Third instance of this shape after release-local logs/ (#569) and the two
holdings copies (#570): a writer whose path resolves from its own cwd, and a
reader on the canonical path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.portfolio_stops import save_risk_state  # noqa: E402


def test_it_writes_both_the_caller_path_and_the_canonical_path(tmp_path, monkeypatch):
    caller = tmp_path / "checkout" / "data" / "portfolios" / "state"
    canon = tmp_path / "persistent" / "data" / "portfolios" / "state"
    caller.mkdir(parents=True)
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir", lambda: canon)

    save_risk_state({"stop_count": 26, "total_unprotected_mv": 650158.77}, caller)

    for d in (caller, canon):
        f = d / "risk_management.json"
        assert f.is_file(), f"missing at {d}"
        assert json.loads(f.read_text())["stop_count"] == 26


def test_both_copies_are_byte_identical(tmp_path, monkeypatch):
    """Written from one in-memory object, so they cannot diverge."""
    caller = tmp_path / "a"; canon = tmp_path / "b"
    caller.mkdir()
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir", lambda: canon)
    save_risk_state({"positions": [{"symbol": "X"}], "stop_count": 3}, caller)
    assert (caller / "risk_management.json").read_bytes() == \
           (canon / "risk_management.json").read_bytes()


def test_the_caller_path_is_still_written(tmp_path, monkeypatch):
    """Not additive otherwise: portfolio_signals, portfolio_weekly_report and
    event_detector all read the checkout tree under `cd $PROJ` and would
    silently freeze if it stopped being written."""
    caller = tmp_path / "a"; caller.mkdir()
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir",
                        lambda: tmp_path / "b")
    save_risk_state({"stop_count": 1}, caller)
    assert (caller / "risk_management.json").is_file()


def test_one_destination_failing_does_not_lose_the_other(tmp_path, monkeypatch):
    """A second destination must never break the first."""
    caller = tmp_path / "a"; caller.mkdir()
    # a path that cannot be created: a file where a directory must go
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file")
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir",
                        lambda: blocked / "state")
    save_risk_state({"stop_count": 7}, caller)
    assert json.loads((caller / "risk_management.json").read_text())["stop_count"] == 7


def test_an_unresolvable_canonical_root_is_not_fatal(tmp_path, monkeypatch):
    caller = tmp_path / "a"; caller.mkdir()
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir", lambda: None)
    save_risk_state({"stop_count": 2}, caller)
    assert (caller / "risk_management.json").is_file()


def test_the_same_path_is_not_written_twice(tmp_path, monkeypatch):
    same = tmp_path / "a"; same.mkdir()
    monkeypatch.setattr("scripts.portfolio_stops._canonical_state_dir", lambda: same)
    save_risk_state({"stop_count": 9}, same)
    assert json.loads((same / "risk_management.json").read_text())["stop_count"] == 9
