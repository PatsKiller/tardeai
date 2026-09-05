"""C5 — declared cadence versus observed output, for operator-surface stores.

strategy_signals stopped advancing on 2026-08-07 and nothing watched the date.
Three detectors reported nothing for 24 days.

These tests also pin the thing that makes this an EXTENSION rather than a second
monitor: every verdict must come from lane_registry.evaluate_lane.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import lane_registry as LR            # noqa: E402
import report_store_cadence as RSC    # noqa: E402

STORES = ROOT / "config" / "operator_surface_stores.json"
FOUND = {"cron": [{"expression": "trade_ai_orchestrator.py"},
                  {"expression": "social_scalp_scanner.py"},
                  {"expression": "signal_fusion.py"},
                  {"expression": "news_to_catalyst.py"}],
         "systemd": []}


def _rows():
    return json.loads(STORES.read_text(encoding="utf-8"))["lanes"]


def test_every_declared_store_is_a_valid_registry_row():
    """The rows must satisfy the SHARED validator, not a private one."""
    errs = []
    for row in _rows():
        errs += LR.validate_row(row)
    assert not errs, "invalid store rows:\n" + "\n".join(f"  {e}" for e in errs)


def test_this_is_an_extension_not_a_second_monitor():
    """§13.5. The verdict must come from the existing evaluator."""
    src = (ROOT / "scripts" / "report_store_cadence.py").read_text(encoding="utf-8")
    assert "lane_registry" in src
    assert "evaluate_lane" in src
    for reimplemented in ("def evaluate_lane", "SLOW =", "EXPECTED_SILENT ="):
        assert reimplemented not in src, (
            f"report_store_cadence re-implements {reimplemented!r} instead of importing "
            "it — that is the parallel mechanism §13.5 exists to prevent"
        )


def test_the_momentum_scalp_row_is_scoped():
    """An aggregate cadence check cannot see a per-strategy cliff.

    paper_trade_proposals reads LIVE because other strategies keep writing it,
    while momentum_scalp stopped 2026-06-30. Same shape as an audit reading OK
    because zero input makes its condition false.
    """
    scoped = [r for r in _rows()
              if (r.get("output_signal") or {}).get("where")
              and "momentum_scalp" in str((r.get("output_signal") or {}).get("where"))]
    assert scoped, "the momentum_scalp-scoped proposals row is gone; the aggregate hides the cliff"


# ── the monitor must be proven able to report each verdict ───────────────────
def _one_row(**over):
    row = {"lane_id": "probe", "owner": "t", "state": "ACTIVE",
           "scheduler": {"kind": "cron", "expression": "trade_ai_orchestrator.py",
                         "match": "trade_ai_orchestrator.py"},
           "expected_cadence_hours": 12,
           "output_signal": {"kind": "db_max", "table": "probe_tbl", "column": "created_at"}}
    row.update(over)
    return row


def _q(ts):
    return lambda sql: [[ts]]


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)   # a Monday


def test_positive_control_a_stale_store_is_SILENT():
    """The 24-day outage: 581h against a 12h cadence."""
    v = LR.evaluate_lane(_one_row(), now=NOW, found=FOUND,
                         db_query=_q(NOW - timedelta(hours=581)))
    assert v["verdict"] == "SILENT", v


def test_positive_control_a_fresh_store_is_LIVE():
    v = LR.evaluate_lane(_one_row(), now=NOW, found=FOUND,
                         db_query=_q(NOW - timedelta(hours=1)))
    assert v["verdict"] == "LIVE", v


def test_positive_control_between_one_and_two_cadences_is_SLOW():
    v = LR.evaluate_lane(_one_row(), now=NOW, found=FOUND,
                         db_query=_q(NOW - timedelta(hours=18)))
    assert v["verdict"] == "SLOW", v


def test_unreadable_signal_is_not_reported_as_SILENT():
    """Conflating 'cannot read' with 'is silent' is how a monitor starts lying."""
    v = LR.evaluate_lane(_one_row(), now=NOW, found=FOUND, db_query=None)
    assert v["verdict"] != "SILENT", v


def test_a_missing_scheduler_is_ORPHANED():
    """The verdict that would have caught a retirement within one cadence period."""
    v = LR.evaluate_lane(_one_row(), now=NOW, found={"cron": [], "systemd": []},
                         db_query=_q(NOW - timedelta(hours=1)))
    assert v["verdict"] == "ORPHANED", v


def test_findings_are_actually_flagged_not_just_labelled():
    """A verdict nobody counts is the defect repeating.

    Pin ``now`` to a weekday inside ``active_days``. Without that pin, a
    weekend CI run (or Friday UTC rolling into Saturday) marks every stale
    store EXPECTED_SILENT / ok=True and this positive control goes blind.
    """
    out = RSC.evaluate(
        STORES, db_query=_q(NOW - timedelta(hours=900)), found=FOUND, now=NOW
    )
    assert out["findings"] > 0
    assert all(r["verdict"] == "SILENT" for r in out["results"] if not r["ok"])
