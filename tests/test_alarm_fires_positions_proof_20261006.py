"""Firing test (2026-10-06) for the positions phase-2 proof report.

scripts/positions_proof_daily.py --send posts one line ("Positions proof day N of 10 ...") to the operator
through the real telegram_alert.send_telegram chokepoint. Fakes only: no database, no broker.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import positions_proof_daily as pd  # noqa: E402

COVERS = ["scripts/positions_proof_daily.py"]
ET = ZoneInfo("America/New_York")


class _Cur:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def cursor(self):
        return _Cur()

    def rollback(self):
        pass


def _setup(tmp_path, monkeypatch, diffs):
    base = datetime(2026, 10, 7, 9, 24, tzinfo=ET)
    runs = [{"run_id": i, "status": "complete", "promoted": True, "finished_at": base + timedelta(minutes=m)}
            for i, m in enumerate(range(0, 7 * 60 + 1, 15))]
    monkeypatch.setattr(pd, "ROOT", tmp_path)
    monkeypatch.setattr(pd.ps, "_conn", lambda: _Conn())
    monkeypatch.setattr(pd, "read_day", lambda cur, day: (runs, diffs, []))


def test_a_passing_day_reports_day_1_of_10(alarm_capture, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [])
    assert pd.main(["--date", "2026-10-07", "--send"]) == 0
    alarm_capture.assert_fired(contains="Positions proof day 1 of 10 PASS")


def test_a_failing_day_reports_the_failed_check(alarm_capture, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [{"account_key": "schwab_taxable", "symbol": "PFLT", "issue": "qty"}])
    assert pd.main(["--date", "2026-10-07", "--send"]) == 1
    alarm_capture.assert_fired(contains="Positions proof FAIL (diff)")


def test_without_send_nothing_reaches_the_transport(alarm_capture, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, [])
    pd.main(["--date", "2026-10-07"])
    assert not alarm_capture.fired
