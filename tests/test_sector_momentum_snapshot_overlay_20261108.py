"""LQ-20261107-1137(a): /api/v2/defense/posture serves the sector snapshot without a per-request DB scan.

Before: every call of get_sector_momentum_snapshot(db_query=...) ran get_sector_signals, a ticker_prices
scan, so the Defense desk's latency followed DB load. Now the overlay is memoized per db_query: computed
inline once per process, then served from memory, refreshed by one background thread when older than
SIGNALS_TTL_S, and the rows say which they got.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from lib.data_broker import sector_momentum as projection

NOW = datetime(2026, 10, 24, 22, tzinfo=timezone.utc)


def _rows():
    days = [d for d in (date(2026, 7, 1) + timedelta(days=i) for i in range(115)) if d.weekday() < 5][-71:]
    return [{"symbol": s, "price_date": d, "close_price": p}
            for i, d in enumerate(days) for s, p in (("SPY", 100 + i * .1), ("XLK", 130 - i * .3))]


class CountingDB:
    """A fake db_query that counts ticker_prices scans (the per-request cost this item removes)."""

    def __init__(self, fail=False):
        self.scans, self.fail, self.rows = 0, fail, _rows()

    def __call__(self, sql, params=None, fetch=None):
        assert sql.lstrip().upper().startswith("SELECT")
        if "ticker_prices" in sql:
            self.scans += 1
            if self.fail:
                raise RuntimeError("canceling statement due to statement timeout")
            return [r for r in self.rows if r["symbol"] in params[0]]
        return []


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    (tmp_path / "sector_momentum_latest.json").write_text(json.dumps({
        "generated_at": "2026-10-20T21:00:00Z",
        "rows": [{"etf": "XLK", "sector": "Technology", "state": "LEADING", "rs20": 9, "rs60": 10,
                  "as_of": "2026-10-20", "breadth_pct": 60}]}))
    monkeypatch.setattr(projection, "_signals_memo", {})
    clock = {"t": 1000.0}
    monkeypatch.setattr(projection.time, "monotonic", lambda: clock["t"])
    spawned = []
    monkeypatch.setattr(projection, "_spawn", spawned.append)  # capture; the test decides when it runs
    return tmp_path, clock, spawned


def _read(tmp_path, db):
    return projection.get_sector_momentum_snapshot(runtime_dir=tmp_path, now=NOW, db_query=db)


def test_only_the_first_read_in_a_process_scans_the_db(runtime):
    tmp_path, clock, spawned = runtime
    db = CountingDB()
    first = _read(tmp_path, db)["snapshot"]
    assert db.scans == 1 and first["signals_overlay"]["state"] == "inline"
    assert first["rows"][0]["state"] == "LAGGING"  # the overlay is applied, as before
    for _ in range(20):
        clock["t"] += 10
        again = _read(tmp_path, db)["snapshot"]
    assert db.scans == 1, "a warm read must never scan ticker_prices on the request"
    assert again["signals_overlay"]["state"] == "fresh" and again["rows"][0]["state"] == "LAGGING"
    assert again["signals_as_of"] == first["signals_as_of"] and spawned == []


def test_an_expired_memo_is_served_marked_stale_and_refreshed_once_off_request(runtime):
    tmp_path, clock, spawned = runtime
    db = CountingDB()
    _read(tmp_path, db)
    clock["t"] += projection.SIGNALS_TTL_S + 1
    stale = [_read(tmp_path, db)["snapshot"] for _ in range(5)]
    assert db.scans == 1, "the request served the old memo and did not wait for the DB"
    assert all(s["signals_overlay"]["state"] == "stale" and s["signals_overlay"]["refreshing"] for s in stale)
    assert stale[0]["signals_overlay"]["age_s"] == pytest.approx(projection.SIGNALS_TTL_S + 1)
    assert len(spawned) == 1, "five concurrent stale reads start ONE refresh"
    spawned.pop()()  # the background refresh runs
    assert db.scans == 2
    fresh = _read(tmp_path, db)["snapshot"]["signals_overlay"]
    assert fresh["state"] == "fresh" and fresh["age_s"] == 0 and not fresh["refreshing"]


def test_a_failed_refresh_keeps_serving_the_last_memo_with_its_error_and_age(runtime):
    tmp_path, clock, spawned = runtime
    db = CountingDB()
    _read(tmp_path, db)
    db.fail = True
    clock["t"] += projection.SIGNALS_TTL_S + 1
    _read(tmp_path, db)
    spawned.pop()()
    clock["t"] += 60
    served = _read(tmp_path, db)["snapshot"]
    overlay = served["signals_overlay"]
    assert overlay["state"] == "stale" and "statement timeout" in overlay["error"]
    assert overlay["age_s"] == pytest.approx(projection.SIGNALS_TTL_S + 61)
    assert served["rows"][0]["state"] == "LAGGING"  # last good overlay, labelled stale, not dropped
    assert len(spawned) == 1, "the next stale read retries once more, still off-request"


def test_a_cold_db_failure_serves_the_snapshot_rows_unoverlaid_and_says_so(runtime):
    tmp_path, _, spawned = runtime
    response = _read(tmp_path, CountingDB(fail=True))
    snap = response["snapshot"]
    assert snap["rows"][0]["rs20"] == 9 and "signals_as_of" not in snap
    assert snap["signals_overlay"]["state"] == "unavailable" and "statement timeout" in snap["signals_overlay"]["error"]
    assert response["stale"] is True  # the envelope still ages the file itself (generated 4 days before NOW)


def test_without_db_query_nothing_changes(runtime):
    tmp_path, _, _ = runtime
    snap = projection.get_sector_momentum_snapshot(runtime_dir=tmp_path, now=NOW)["snapshot"]
    assert "signals_overlay" not in snap and snap["rows"][0]["rs20"] == 9


def test_the_real_spawn_runs_the_refresh_on_a_daemon_thread(monkeypatch):
    import threading
    seen = threading.Event()
    projection._spawn(lambda: seen.set() if threading.current_thread().daemon else None)
    assert seen.wait(5)
