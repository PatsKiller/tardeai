"""LQ-20261107-1706: an undated bar source settled every due watch event as NOT_EVALUABLE and reported green.

``_closes`` builds its series from ``b["datetime"] / b["t"] / b["date"]``; a source that returns the
``holding_protection_advisor._bars`` yfinance shape (``{"open","high","low","close"}``, no date) yields an
empty series, so ``_ret_after`` returned None, the lane wrote ``verdict='NOT_EVALUABLE'`` — which takes the
row out of the ``verdict IS NULL`` selector for good — and the receipt said ``produced=N``, exit 0.

Pins (fail before, pass after):

* a symbol or SPY series with no dated bar is a ``bars_unavailable`` skip: verdict stays NULL (retryable),
  no UPDATE is issued for that row, nothing is counted as produced;
* a run whose only obstacle was the bar source exits 1 with ``dependency_unavailable``;
* the dated control scores the same rows, and ``[]`` (a datable series with no positive close) keeps its
  old meaning — it is not the same answer as ``None``.

Hermetic: fake ``db_adapter``, stubbed ``_closes``, receipt writer captured, no DB, no network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str = "reconcile_watch_outcomes"):
    spec = importlib.util.spec_from_file_location(f"lq1706_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def receipts(monkeypatch):
    import lib.lane_last_receipt as llr

    calls: list[dict] = []
    monkeypatch.setattr(llr, "write_lane_receipt", lambda lane_id, **kw: calls.append({"lane_id": lane_id, **kw}))
    return calls


ROWS = [{"id": 1, "symbol": "AAPL", "emitted_on": dt.date(2026, 9, 1), "anchor_price": 100.0},
        {"id": 2, "symbol": "MSFT", "emitted_on": dt.date(2026, 9, 1), "anchor_price": 200.0}]


def _db(monkeypatch, rows=ROWS):
    """Answers the lane's statements; records every per-event UPDATE so a skipped row is provable."""
    updates: list[tuple] = []

    def execute(sql, params=None, fetch=None):
        s = " ".join(sql.split()).lower()
        if s.startswith("select id, symbol"):
            return list(rows)
        if s.startswith("update watch_candidate_events"):
            if "set ret_21d" in s:                 # the per-event settlement, not the unanchored sweep
                updates.append(tuple(params or ()))
            return None
        if s.startswith("select source_type"):
            return []
        raise AssertionError(f"unexpected SQL: {s[:80]}")

    stub = types.ModuleType("db_adapter")
    stub._execute = execute
    stub.USE_DB = True
    monkeypatch.setitem(sys.modules, "db_adapter", stub)
    return updates


def _dated_seq(start: dt.date, n: int = 90):
    return [(start + dt.timedelta(days=i), 100.0 + i * 0.1) for i in range(n)]


# ----------------------------------------------------------------------------------------------------------
# the defect
# ----------------------------------------------------------------------------------------------------------

def test_no_dated_bars_skip_the_events_and_fail_naming_the_source(monkeypatch, receipts, capsys):
    mod = _load()
    updates = _db(monkeypatch)
    monkeypatch.setattr(mod, "_closes", lambda symbol, cache: None)

    assert mod.main() == 1
    err = capsys.readouterr().err
    assert "bars_unavailable" in err and "all_skipped" in err
    assert updates == []                       # no verdict was written, so every event is retryable
    r = receipts[0]
    assert r["ok"] is False
    assert r["empty_reason"] == "dependency_unavailable"
    assert r["produced_count"] == 0
    assert r["skipped_reasons"] == {"bars_unavailable": 2}


def test_dated_bars_are_the_green_control(monkeypatch, receipts):
    mod = _load()
    updates = _db(monkeypatch)
    seq = _dated_seq(dt.date(2026, 8, 25))
    monkeypatch.setattr(mod, "_closes", lambda symbol, cache: seq)

    assert mod.main() == 0
    assert len(updates) == 2                   # one UPDATE per event, verdict included
    assert updates[0][-1] == 1 and updates[0][-2] in {"OUTPERFORM", "UNDERPERFORM", "MARKET"}
    r = receipts[0]
    assert r["ok"] is True and r["produced_count"] == 2


def test_spy_undated_alone_is_the_same_failure(monkeypatch, receipts):
    """SPY is fetched once, before the loop: if its source is undatable, no alpha exists for any event."""
    mod = _load()
    updates = _db(monkeypatch)
    seq = _dated_seq(dt.date(2026, 8, 25))
    monkeypatch.setattr(mod, "_closes", lambda symbol, cache: None if symbol == "SPY" else seq)

    assert mod.main() == 1
    assert updates == []
    assert receipts[0]["skipped_reasons"] == {"bars_unavailable": 2}


def test_an_empty_dated_series_keeps_its_old_meaning(monkeypatch, receipts):
    """``[]`` is a datable series with nothing positive in it: the event settles NOT_EVALUABLE, as before.
    Only ``None`` (no dated bar at all) is the retryable source failure."""
    mod = _load()
    updates = _db(monkeypatch)
    monkeypatch.setattr(mod, "_closes", lambda symbol, cache: [])

    assert mod.main() == 0
    assert len(updates) == 2
    assert all(u[-2] == "NOT_EVALUABLE" for u in updates)
    r = receipts[0]
    assert r["ok"] is True and r["produced_count"] == 2
    assert (r.get("skipped_reasons") or {}) == {}


def test_closes_returns_none_only_when_nothing_carries_a_date(monkeypatch):
    mod = _load()
    for bars, want in (([{"open": 1, "high": 1, "low": 1, "close": 9.0}], None),
                       ([], None),
                       ([{"date": "2026-11-01", "close": 9.0}], [(dt.date(2026, 11, 1), 9.0)])):
        monkeypatch.setitem(sys.modules, "holdings_gain_guardian",
                            types.SimpleNamespace(_bars_with_volume=lambda symbol, days=0, _b=bars: _b))
        assert mod._closes("AAA", {}) == want
