"""ANCHOR: LOCKUP_SNAP_NEAREST_354_20261107 — the lane snaps the tranche the announcement belongs to.

LQ-20261107-354. Measured 2026-11-07 on the shipped config (`config/ipo_lockups.json`): `plan_snaps`
took the **earliest still-approx** earnings tranche, which was the Q2 tranche estimated 2026-08-05.
The ±75-day window then compared every announced date with that estimate, so:

    announced 2026-11-12 -> changed=[]      announced 2027-01-28 -> changed=[]
    announced 2026-08-06 -> changed=[2026-08-05 -> 2026-08-10]

The lane could therefore only ever "snap" a tranche three months in the past. It now picks the
estimate nearest the announced date inside the window, preferring a still-future estimate only when
two are equally near — an announcement that lands days AFTER its own estimate must still snap that
group, or that tranche could never be snapped at all, and a delayed report must still snap the
quarter it belongs to rather than whichever estimate happens to be in the future.

Dates are built relative to `date.today()` so the suite stays true whenever it runs.

COVERS: scripts/update_lockup_earnings_dates.py::plan_snaps
COVERS: scripts/update_lockup_earnings_dates.py::_tranche_day

Hermetic: synthetic configs, a stubbed `_next_earnings`, no file read, no write, no database.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import update_lockup_earnings_dates as U  # noqa: E402

TODAY = date.today()
SYM = "SYN"


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _tranche(offset: int, desc: str = "Q earnings (estimate)", approx: bool = True) -> dict:
    return {"date": _day(offset), "approx": approx, "desc": desc}


def _cfg(*tranches: dict) -> dict:
    return {"lockups": {SYM: {"tranches": list(tranches)}}}


@pytest.fixture()
def announced(monkeypatch):
    """Stub the yfinance lookup: the announcement is whatever the test names, never the network."""
    def _set(offset: int) -> date:
        d = TODAY + timedelta(days=offset)
        monkeypatch.setattr(U, "_next_earnings", lambda sym: d)
        return d
    return _set


def _release(d: date) -> str:
    return U._plus_trading_days(d, 2).isoformat()


# --------------------------------------------------------------------------- the reported defect


def test_an_announcement_after_its_own_estimate_snaps_that_group(announced):
    """The Q3 case: estimate five days ago, report lands five days from now, an older estimate exists."""
    ed = announced(5)
    cfg = _cfg(_tranche(-90, "Q2 earnings"), _tranche(-5, "Q3 earnings"))
    changed = U.plan_snaps(cfg)
    assert changed == [{"symbol": SYM, "from": _day(-5), "to": _release(ed), "earnings": ed.isoformat(),
                        "tranches": 1}]


def test_a_stale_estimate_is_never_the_one_snapped(announced):
    """The old code picked this row (earliest) and then rejected the announcement as too far away."""
    ed = announced(5)
    cfg = _cfg(_tranche(-90, "Q2 earnings"), _tranche(-5, "Q3 earnings"))
    U.plan_snaps(cfg)
    old = next(t for t in cfg["lockups"][SYM]["tranches"] if t["date"] == _day(-90))
    assert old["approx"] is True, "a tranche 90 days in the past must not be retroactively rewritten"


def test_an_announcement_before_a_future_estimate_snaps_it(announced):
    """The Q4 case that also returned changed=[] before the fix."""
    ed = announced(30)
    cfg = _cfg(_tranche(-90, "Q2 earnings"), _tranche(35, "Q4 earnings"))
    changed = U.plan_snaps(cfg)
    assert [c["from"] for c in changed] == [_day(35)]
    assert changed[0]["to"] == _release(ed)


def test_the_whole_group_moves_and_non_approx_rows_at_that_date_do_not(announced):
    ed = announced(2)
    cfg = _cfg(_tranche(-5, "Q3 earnings"),
               _tranche(-5, "BONUS at Q3 earnings"),
               _tranche(-5, "Day 70 — a fixed tranche", approx=False))
    changed = U.plan_snaps(cfg)
    assert changed[0]["tranches"] == 2
    rows = cfg["lockups"][SYM]["tranches"]
    assert [t["approx"] for t in rows] == [False, False, False]
    assert next(t for t in rows if "Day 70" in t["desc"])["date"] == _day(-5)


# --------------------------------------------------------------------------- controls


def test_no_estimate_inside_the_window_changes_nothing(announced):
    """Control: the window still refuses a quarter the announcement does not belong to."""
    announced(0)
    cfg = _cfg(_tranche(-200, "Q2 earnings"))
    assert U.plan_snaps(cfg) == []


def test_no_announcement_changes_nothing(monkeypatch):
    monkeypatch.setattr(U, "_next_earnings", lambda sym: None)
    assert U.plan_snaps(_cfg(_tranche(-5, "Q3 earnings"))) == []


def test_an_already_correct_group_is_not_rewritten(monkeypatch):
    """Idempotence: the second run of the same announcement must be a no-op."""
    ed = TODAY + timedelta(days=2)
    monkeypatch.setattr(U, "_next_earnings", lambda sym: ed)
    cfg = _cfg(_tranche(-5, "Q3 earnings"))
    cfg["lockups"][SYM]["tranches"][0]["date"] = _release(ed)
    assert U.plan_snaps(cfg) == []


def test_an_unparseable_estimate_is_skipped_not_fatal(announced):
    announced(2)
    cfg = _cfg({"date": "TBD", "approx": True, "desc": "Q3 earnings"}, _tranche(-5, "Q3 earnings"))
    changed = U.plan_snaps(cfg)
    assert [c["from"] for c in changed] == [_day(-5)]


def test_equal_distance_prefers_the_still_future_estimate(announced):
    """Tie-break, stated as a rule: a past estimate must not win a tie against a future one."""
    ed = announced(0)
    cfg = _cfg(_tranche(-10, "Q3 earnings"), _tranche(10, "Q4 earnings"))
    changed = U.plan_snaps(cfg)
    assert [c["from"] for c in changed] == [_day(10)]


def test_a_delayed_report_still_snaps_its_own_past_estimate(announced):
    """The future preference is a tie-break only: it must never override a nearer passed estimate.

    A Q3 report that slips a month still belongs to the Q3 group, even though the Q4 estimate is
    also inside the window. Preferring any future estimate would snap the wrong quarter here.
    """
    ed = announced(0)
    cfg = _cfg(_tranche(-10, "Q3 earnings"), _tranche(40, "Q4 earnings"))
    changed = U.plan_snaps(cfg)
    assert [c["from"] for c in changed] == [_day(-10)]
