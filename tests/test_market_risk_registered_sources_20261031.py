"""Engine inputs from already-registered sources (Schwab chain snapshots, Finviz enrichment) — hermetic."""

import json
import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.market_risk import contract
from scripts.lib.market_risk import registered_sources as rs

ET = ZoneInfo("America/New_York")


def _snap(sym, ts, px, iv):
    return {"symbol": sym, "as_of": ts, "underlying_price": px, "atm_iv": iv, "source": "option_chain_snapshots"}


def test_implied_move_uses_newest_snapshot_and_percent_iv():
    rows = [
        _snap("ETF-A", "2026-10-29T10:00:00-04:00", 40.0, 30.0),
        _snap("ETF-A", "2026-10-30T17:35:00-04:00", 43.0, 23.7),
    ]
    m = rs.implied_moves(rows, sessions=5)["ETF-A"]
    assert m["move_pct"] == pytest.approx(23.7 * math.sqrt(5 / 252), abs=0.01)
    assert m["underlying"] == 43.0 and m["as_of"].startswith("2026-10-30")
    contract.assert_no_behavior_fields(m)


def test_implied_move_skips_unusable_rows_unknown_not_zero():
    rows = [
        _snap("ETF-B", "2026-10-30T17:35:00-04:00", None, 20.0),
        _snap("ETF-C", "2026-10-30T17:35:00-04:00", 10.0, 0),
    ]
    assert rs.implied_moves(rows, sessions=1) == {}
    with pytest.raises(ValueError):
        rs.implied_moves(rows, sessions=0)


def test_chain_close_is_earliest_snapshot_in_close_window_on_trading_day():
    rows = [
        _snap("ETF-D", "2026-10-30T10:00:00-04:00", 41.0, 20.0),
        _snap("ETF-D", "2026-10-30T16:02:00-04:00", 43.10, 20.0),
        _snap("ETF-D", "2026-10-30T16:10:00-04:00", 43.12, 20.0),
        _snap("ETF-D", "2026-10-30T17:35:00-04:00", 43.30, 20.0),
        _snap("ETF-D", "2026-10-31T16:05:00-04:00", 44.00, 20.0),
    ]
    out = rs.chain_daily_closes(rows)
    assert out == [
        {
            "symbol": "ETF-D",
            "session_date": "2026-10-30",
            "close": 43.10,
            "as_of": "2026-10-30T16:02:00-04:00",
            "source": "provisional_chain_snapshot",
        }
    ]


def test_chain_close_ignores_after_hours_only_days_and_honours_early_close():
    # 17:35 after-hours print only: no close (SPY 756.32 vs official 755.72 case)
    assert rs.chain_daily_closes([_snap("SPY", "2026-10-30T17:35:00-04:00", 756.32, 15.0)]) == []
    # 2026-11-27 closes 13:00 — a 13:05 snapshot is the close, a 16:05 one is not
    out = rs.chain_daily_closes(
        [
            _snap("ETF-E", "2026-11-27T13:05:00-05:00", 10.0, 20.0),
            _snap("ETF-F", "2026-11-27T16:05:00-05:00", 11.0, 20.0),
        ]
    )
    assert [r["symbol"] for r in out] == ["ETF-E"]


def test_implied_move_flags_iv_out_of_line_with_trailing_median():
    hist = [_snap("ETF-X", f"2026-10-{d:02d}T10:00:00-04:00", 99.0, 25.0) for d in range(19, 29)]
    spike = hist + [_snap("ETF-X", "2026-10-30T17:35:00-04:00", 99.57, 71.84)]
    m = rs.implied_moves(spike, sessions=5)["ETF-X"]
    assert m["dq_flags"] and m["dq_flags"][0].startswith("iv_out_of_line")
    calm = hist + [_snap("ETF-X", "2026-10-30T17:35:00-04:00", 99.57, 27.0)]
    assert rs.implied_moves(calm, sessions=5)["ETF-X"]["dq_flags"] == []
    assert rs.implied_moves([_snap("ETF-Y", "2026-10-30T17:35:00-04:00", 10.0, 20.0)], sessions=5)["ETF-Y"][
        "dq_flags"
    ] == ["iv_history_short"]


def test_finviz_positioning_respects_cached_at(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text(
        json.dumps(
            {
                "STOCK-A": {
                    "cached_at": "2026-10-29T12:00:00-04:00",
                    "inst_trans_pct": -1.5,
                    "short_float_pct": 3.2,
                    "sma50_pct": -4.0,
                },
                "STOCK-B": {"cached_at": "2026-10-31T09:00:00-04:00", "inst_trans_pct": 2.0},
                "STOCK-C": {"cached_at": "2026-10-29T12:00:00-04:00"},
                "STOCK-D": {
                    "cached_at": "2026-10-29T12:00:00-04:00",
                    "hot_cached_at": "2026-10-31T09:00:00-04:00",
                    "rvol": 3.0,
                    "inst_trans_pct": 1.0,
                },
            }
        )
    )
    end = datetime(2026, 10, 30, 18, 0, tzinfo=ET)
    out = rs.finviz_positioning(["STOCK-A", "STOCK-B", "STOCK-C", "STOCK-D", "STOCK-Z"], end=end, path=p)
    assert set(out) == {"STOCK-A"}
    assert out["STOCK-A"]["inst_trans_pct"] == -1.5 and out["STOCK-A"]["source"] == "finviz_enrichment_cache"
    contract.assert_no_behavior_fields(out)


def test_finviz_positioning_unreadable_cache_is_loud(tmp_path):
    p = tmp_path / "cache.json"
    p.write_text("{not json")
    with pytest.raises(RuntimeError):
        rs.finviz_positioning(["X"], end=datetime(2026, 10, 30, tzinfo=ET), path=p)
    assert rs.finviz_positioning(["X"], end=datetime(2026, 10, 30, tzinfo=ET), path=tmp_path / "missing.json") == {}
