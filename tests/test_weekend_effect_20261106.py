"""PKG-SELLOFF-INTEL-20261106 D: the weekend effect is MEASURED from history, never assumed.

The operator asked whether a Friday selloff carries into Monday. The package says: measure it, under the same stress
conditions as the other base rates, and report it as a fact with n, median, the share of weekends that ended lower,
and the date range; if n is too small, say so. These tests pin that:

* the build flags exactly the plain Friday -> Monday weekends (no holiday weekends) and records the next session's open;
* ``base_rates.weekend`` computes the figures from whatever the table holds: flip the synthetic data and the answer
  flips (nothing is hard-coded), with the same backoff and a same-conditions baseline of every other session;
* the deep brief states it Friday to Sunday only, with n, median, share lower and range, or "too few" with the count.

Synthetic fixtures only (invented returns on public index tickers, no holdings, no account data). No network, no DB.
"""

from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.lib.market_risk import base_rates as br
from scripts.lib.market_risk import deep_brief_facts as dbf

ROOT = Path(__file__).resolve().parents[1]


def _build_mod():
    spec = importlib.util.spec_from_file_location("brb_wk", ROOT / "scripts" / "market_risk_base_rates_build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- the build ----------------------------------------------------------------------------------------------------


def test_only_plain_friday_to_monday_is_a_weekend():
    mod = _build_mod()
    fri, mon = date(2024, 3, 1), date(2024, 3, 4)
    assert mod.is_weekend_gap(fri, mon)
    assert not mod.is_weekend_gap(date(2024, 2, 29), mon)  # Thursday -> Monday (holiday Friday)
    assert not mod.is_weekend_gap(fri, date(2024, 3, 5))  # Friday -> Tuesday (holiday Monday)
    assert not mod.is_weekend_gap(date(2024, 3, 4), date(2024, 3, 5))  # an ordinary night


def test_build_flags_weekends_and_records_the_next_open():
    mod = _build_mod()
    days, x = [], date(2025, 6, 2)
    holiday = date(2025, 7, 4)  # a Friday holiday: Thursday 07-03 -> Monday 07-07 is NOT a plain weekend
    while x < date(2026, 2, 1):
        if x.weekday() < 5 and x != holiday:
            days.append(x)
        x += timedelta(days=1)
    by = {s: {d: 100.0 + i * 0.1 for i, d in enumerate(days)} for s in mod.SYMBOLS}
    opens = {s: {d: 100.0 + i * 0.1 - 0.05 for i, d in enumerate(days)} for s in br.INDEXES}
    t = mod.build(days, by, opens)
    rows = {r["d"]: r for r in t["rows"]}
    wk = [r["d"] for r in t["rows"] if r.get("wk") == 1]
    assert wk and all(date.fromisoformat(d).weekday() == 4 for d in wk)
    assert "2025-07-03" not in wk  # the Thursday before the holiday
    # every in-sample Friday whose Monday is in sample is flagged, except none other
    fridays = [d for d in days if d.weekday() == 4 and d + timedelta(days=3) in days and d.year == 2025]
    assert sorted(wk) == sorted(d.isoformat() for d in fridays)
    # next open vs this close: (100 + (i+1)*0.1 - 0.05) / (100 + i*0.1) - 1
    i = days.index(date(2025, 9, 5))
    assert rows["2025-09-05"]["o"]["SPY"]["o1"] == round((100.0 + (i + 1) * 0.1 - 0.05) / (100.0 + i * 0.1) - 1, 5)
    # the last 2025 row has no next session in sample: no o1, no weekend flag reaching into 2026
    last = t["rows"][-1]
    assert last["d"] == "2025-12-31" and "o1" not in last["o"]["SPY"] and "wk" not in last
    # without opens (an old caller) the build still runs, just with no o1
    assert all("o1" not in r["o"]["SPY"] for r in mod.build(days, by)["rows"])


def test_committed_table_carries_weekends_and_opens():
    t = br.load_table()
    wk = [r for r in t["rows"] if r.get("wk") == 1]
    assert len(wk) > 400, "ten years of plain weekends"
    assert all(date.fromisoformat(r["d"]).weekday() == 4 for r in wk)
    assert sum(1 for r in wk if r["o"]["SPY"].get("o1") is not None) == len(wk)


# -- the measure --------------------------------------------------------------------------------------------------


def _row(d: date, pattern: str, vix_b: str, close: float, opn: float | None, wk: bool) -> dict:
    o = {"SPY": {"1": close}, "QQQ": {"1": close * 1.5}}
    if opn is not None:
        o["SPY"]["o1"], o["QQQ"]["o1"] = opn, opn * 1.5
    r = {"d": d.isoformat(), "f": {"pattern": pattern, "vix_b": vix_b}, "o": o}
    if wk:
        r["wk"] = 1
    return r


def _table(weekend_close: float, weekend_open: float, n_broad: int = 24, n_high: int = 5) -> dict:
    """``n_broad`` BROAD weekends (``n_high`` of them at vix_b 30+), 60 BROAD ordinary sessions, 40 MIXED weekends."""
    rows, d = [], date(2030, 1, 4)  # a Friday
    for k in range(n_broad):
        # alternate a little around the target so the median is the target and the share lower is exact
        c = weekend_close + (0.001 if k % 2 else -0.001)
        o = weekend_open + (0.001 if k % 2 else -0.001)
        rows.append(_row(d + timedelta(weeks=k), "BROAD", "30+" if k < n_high else "20-25", c, o, True))
    for k in range(60):
        rows.append(_row(date(2030, 1, 7) + timedelta(weeks=k), "BROAD", "20-25", 0.002, 0.001, False))
    for k in range(40):
        rows.append(_row(date(2031, 1, 3) + timedelta(weeks=k), "MIXED", "<15", 0.004, 0.003, True))
    return {"schema": br.TABLE_SCHEMA, "generated_from": "synthetic", "holdout": "none", "rows": rows}


def test_weekend_reports_n_median_share_lower_and_range_with_a_baseline():
    t = _table(weekend_close=-0.01, weekend_open=-0.02)
    w = br.weekend({"pattern": "BROAD", "vix_b": "30+"}, min_n=20, table=t)
    # only 5 weekends at vix 30+: the backoff drops vix_b (as conditional does) and says so
    assert w["conditions"] == {"pattern": "BROAD"} and w["dropped"] == ["vix_b"]
    assert w["n_weekends"] == 24 and w["weekends_in_table"] == 64
    assert (
        w["first_weekend"] == "2030-01-04" and w["last_weekend"] == (date(2030, 1, 4) + timedelta(weeks=23)).isoformat()
    )
    spy = w["SPY"]
    assert (
        spy["close"]["n"] == 24 and spy["close"]["median_pct"] == -1.0 and spy["close"]["share_negative_pct"] == 100.0
    )
    assert spy["open"]["median_pct"] == -2.0
    assert w["QQQ"]["close"]["median_pct"] == -1.5
    # the baseline is every OTHER session on the same conditions (BROAD ordinary days only, not the MIXED weekends)
    base = w["baseline"]
    assert base["sessions"] == 60
    assert base["SPY"]["close"]["n"] == 60 and base["SPY"]["close"]["median_pct"] == 0.2
    assert base["SPY"]["close"]["share_negative_pct"] == 0.0 and base["SPY"]["open"]["median_pct"] == 0.1


def test_the_answer_follows_the_data_not_a_hypothesis():
    down = br.weekend({"pattern": "BROAD"}, min_n=20, table=_table(-0.01, -0.02))
    up = br.weekend({"pattern": "BROAD"}, min_n=20, table=_table(+0.01, +0.02))
    assert down["SPY"]["close"]["share_negative_pct"] == 100.0 and up["SPY"]["close"]["share_negative_pct"] == 0.0
    assert down["SPY"]["close"]["median_pct"] == -1.0 and up["SPY"]["close"]["median_pct"] == 1.0


def test_too_few_weekends_is_said_with_the_count():
    t = _table(-0.01, -0.02, n_broad=12)
    w = br.weekend({"pattern": "BROAD", "vix_b": "30+"}, min_n=20, table=t)
    assert w["insufficient_history"] is True and w["n_weekends"] == 0
    assert w["n_at_loosest"] == 12 and w["loosest_conditions"] == {"pattern": "BROAD"}
    assert "SPY" not in w


def test_an_old_table_without_opens_marks_the_open_leg_insufficient():
    t = _table(-0.01, -0.02)
    for r in t["rows"]:
        for s in ("SPY", "QQQ"):
            r["o"][s].pop("o1", None)
    w = br.weekend({"pattern": "BROAD"}, min_n=20, table=t)
    assert w["SPY"]["close"]["n"] == 24 and not w["SPY"]["close"].get("insufficient_history")
    assert w["SPY"]["open"] == {"n": 0, "insufficient_history": True}


# -- the deep brief -----------------------------------------------------------------------------------------------

FRI = datetime(2031, 3, 7, 21, 30, tzinfo=timezone.utc)  # Friday 16:30 ET
SUN = datetime(2031, 3, 9, 18, 0, tzinfo=timezone.utc)
WED = datetime(2031, 3, 5, 21, 30, tzinfo=timezone.utc)


def _pack(now, table, monkeypatch, feats=None):
    monkeypatch.setattr(br, "load_table", lambda *a, **k: table)
    p = dbf.Pack(now)
    dbf._weekend(p, feats or {"pattern": "BROAD", "vix_b": "30+"}, now, {"min_n": 20})
    return p


@pytest.mark.parametrize("now", [FRI, SUN])
def test_brief_states_both_legs_as_facts_on_a_weekend(now, monkeypatch):
    p = _pack(now, _table(-0.01, -0.02), monkeypatch)
    assert [f["label"] for f in p.facts] == ["weekend Monday close", "weekend Monday open"]
    close = p.facts[0]["text"]
    assert close.startswith("Friday close to Monday close, 24 plain weekends 2030-01-04 to ")
    assert "on [pattern=BROAD]" in close and "SPY median -1.00%, lower in 100.0%" in close
    assert "QQQ median -1.50%" in close
    assert "Every other session on the same conditions, next close: SPY median +0.20%, lower in 0.0% (n=60)" in close
    assert "Dropped [vix_b] to reach n>=20" in close
    assert "SPY median -2.00%" in p.facts[1]["text"]
    assert all(f["section"] == "next" and f["source"] == "base_rates_table" for f in p.facts)
    assert not p.unknown


def test_brief_is_silent_midweek(monkeypatch):
    p = _pack(WED, _table(-0.01, -0.02), monkeypatch)
    assert not p.facts and not p.unknown


def test_brief_says_too_few_rather_than_a_number(monkeypatch):
    p = _pack(FRI, _table(-0.01, -0.02, n_broad=12), monkeypatch)
    assert not p.facts
    assert p.unknown == [
        {
            "section": "next",
            "what": "weekend effect",
            "reason": "only 12 plain weekends 2016-2025 match [pattern=BROAD] (n<20): "
            "too few to state a Friday-to-Monday effect",
        }
    ]
