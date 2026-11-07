"""portfolio-repricer must report its own run: every exit path writes a LaneRunReceipt.

2026-11-06, WORK-QUEUE item 4: the lane row said ``ok_unverified`` / ``grade=DEGRADED`` with
"receipt reports gaps = 1" while every cron fire exited 0 and refreshed ``holdings.json``.

The cause was two-sided; this file covers the writer side. ``scripts/portfolio_repricer.py``
wrote no lane receipt at all, so the run-quality grader fell back to the lane's declared
``output_signal`` — ``data/portfolios/state/holdings.json`` — whose top-level ``gaps`` is a
STANDING data note ("fund look-through unavailable: etf_holdings_snapshot is not applied"),
never a per-run gap. Nothing in the lane's own history ever reported a gap.

The reader side (the grader preferring ``data/runtime/<lane>_last.json`` over a declared business
store) is ``tests/test_run_quality_lane_receipt_precedence_20261107.py``.

Synthetic fixtures only: no live store, no broker, no network, no quotes fetched — ``main()`` is
never allowed past its missing-file guard here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import portfolio_repricer as repricer  # noqa: E402
from scripts.lib import run_quality as rq  # noqa: E402


def _state_dir(root: Path) -> Path:
    d = root / "data" / "portfolios" / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _receipt(root: Path) -> Path:
    return root / "data" / "runtime" / "portfolio-repricer_last.json"


def test_missing_holdings_writes_a_failed_receipt(tmp_path):
    """A run that cannot find its book still reports: failed, exit 1, and no fresh ok_at."""
    state = _state_dir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        repricer.main([state])
    assert exc.value.code == 1
    doc = json.loads(_receipt(tmp_path).read_text(encoding="utf-8"))
    assert doc["lane_id"] == "portfolio-repricer"
    assert doc["status"] == "failed"
    assert doc["exit"] == 1
    assert doc["ok_at"] is None          # a failure never advances the green stamp
    assert doc["mode"] == "live"


def test_a_failed_run_does_not_advance_ok_at(tmp_path):
    """The previous good run stays the last green stamp: a failure goes stale, never green."""
    state = _state_dir(tmp_path)
    repricer._write_run_receipt(state, ok=True, exit_code=0, summary={"holdings": 3}, produced_count=3)
    good = json.loads(_receipt(tmp_path).read_text(encoding="utf-8"))
    assert good["ok_at"]
    with pytest.raises(SystemExit):
        repricer.main([state])           # no holdings.json in this fixture
    failed = json.loads(_receipt(tmp_path).read_text(encoding="utf-8"))
    assert failed["status"] == "failed"
    assert failed["ok_at"] == good["ok_at"]
    assert failed["consecutive_failures"] == 1


def test_success_receipt_carries_what_the_run_produced(tmp_path):
    state = _state_dir(tmp_path)
    repricer._write_run_receipt(
        state, started_at="2026-11-07T02:30:00+00:00", ok=True, exit_code=0,
        summary={"holdings": 34, "holdings_updated": 29, "copies_written": 2}, produced_count=34)
    doc = json.loads(_receipt(tmp_path).read_text(encoding="utf-8"))
    assert doc["schema"] == "LaneRunReceipt@v2"
    assert doc["status"] == "ok" and doc["exit"] == 0
    assert doc["produced_count"] == 34 and doc["attempted_count"] == 34
    assert doc["started_at"].startswith("2026-11-07T02:30:00")
    assert doc["ok_at"]
    assert rq.receipt_flags(doc, 34) == []   # a healthy pass states no degradation


def test_the_receipt_lands_beside_the_state_root_it_wrote(tmp_path):
    """The receipt follows the state dir the run actually wrote, not the checkout it ran from."""
    state = _state_dir(tmp_path / "other-root")
    repricer._write_run_receipt(state, ok=True, exit_code=0, summary={"holdings": 1}, produced_count=1)
    assert _receipt(tmp_path / "other-root").is_file()
