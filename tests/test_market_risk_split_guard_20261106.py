"""Split / corporate-action guard (LIVEFIX-S 2026-11-06): an unadjusted split is back-adjusted at the reader, a real
crash is left alone, an ambiguous jump is a stated data gap, and a sector group with one gapped member is scored on
the others. Synthetic numbers and ZZ* symbols only; no DB, no network."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scripts.lib.market_risk import contract as c
from scripts.lib.market_risk import reader as rd
from scripts.lib.market_risk import sectors, split_guard
from scripts.lib.market_risk.policy import load_policy

ET = ZoneInfo("America/New_York")
CFG_BLOCK = {
    "enabled": True,
    "benchmark": "SPY",
    "candidate_min_move_pct": 25,
    "split_ratios": [1.5, 2, 3, 4, 5, 8, 10, 15, 20],
    "include_reverse": True,
    "max_residual_move_pct": 15,
    "confirm_sessions": 1,
}
CFG = split_guard.config(CFG_BLOCK)


def _days(n: int, start: date = date(2026, 6, 1)) -> list[str]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _rows(sym: str, closes: list[float], days: list[str] | None = None) -> list[dict]:
    days = days or _days(len(closes))
    return [{"symbol": sym, "date": d, "close": cl, "source": "market_quotes:alpaca_prev_close"} for d, cl in zip(days, closes)]


# ── pure guard ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_policy_block_is_present_and_valid():
    cfg = split_guard.config((load_policy().get("corporate_actions") or {}).get("split_guard"))
    assert cfg is not None and cfg["benchmark"] == "SPY" and cfg["tolerance"] < cfg["candidate"]


def test_clean_three_for_one_split_is_back_adjusted():
    rows = _rows("ZZA", [300.0, 306.0, 303.0, 91.0, 93.0])  # 303 -> 91 = 0.3003 (3:1 with a ~-10% day)
    peer = {r["date"]: v for r, v in zip(rows, [100.0, 101.0, 100.0, 96.0, 97.0])}  # market -4% that day
    out, rep = split_guard.guard_series(rows, CFG, lambda: peer)
    assert "gap" not in rep
    (a,) = rep["adjustments"]
    assert a["ratio"] == "3:1" and a["factor"] == 3 and a["date"] == rows[3]["date"]
    assert a["confirmed_by"] == [rows[4]["date"]] and a["peer_move_pct"] == -4.0
    assert [round(r["close"], 2) for r in out] == [100.0, 102.0, 101.0, 91.0, 93.0]
    assert out[0]["adjusted_for_split"] == 3 and out[0]["source"].endswith("+split_adj:3")
    assert "adjusted_for_split" not in out[3] and out[3]["source"] == "market_quotes:alpaca_prev_close"
    assert rows[0]["close"] == 300.0  # caller's rows are not mutated


def test_reverse_split_is_back_adjusted():
    rows = _rows("ZZA", [2.0, 2.1, 2.0, 20.5, 20.7])  # 1:10 reverse split
    out, rep = split_guard.guard_series(rows, CFG, None)
    assert rep["adjustments"][0]["ratio"] == "1:10" and round(out[0]["close"], 3) == 20.0


def test_real_twelve_percent_crash_is_not_adjusted():
    rows = _rows("ZZA", [100.0, 101.0, 88.9, 87.0, 88.0])
    out, rep = split_guard.guard_series(rows, CFG, lambda: pytest.fail("peer must not be read without a candidate"))
    assert rep == {"adjustments": []} and out is rows


def test_large_move_matching_no_ratio_is_left_alone():
    rows = _rows("ZZA", [100.0, 100.0, 62.0, 61.0])  # -38%: between 1.5:1 (-33%) and 2:1 (-50%) beyond tolerance
    peer = {r["date"]: 100.0 for r in rows}
    out, rep = split_guard.guard_series(rows, dict(CFG, tolerance=0.05), lambda: peer)
    assert rep == {"adjustments": []} and out is rows


def test_reverted_jump_is_a_gap_with_reason():
    rows = _rows("ZZA", [300.0, 303.0, 101.0, 302.0])  # one bad print, back the next session
    out, rep = split_guard.guard_series(rows, CFG, None)
    assert rep["gap"].startswith("reverted jump:") and "3:1" in rep["gap"] and out is rows


def test_unconfirmed_jump_on_the_latest_session_is_a_gap():
    rows = _rows("ZZA", [300.0, 303.0, 101.0])
    _, rep = split_guard.guard_series(rows, CFG, None)
    assert rep["gap"].startswith("unconfirmed corporate action:")


def test_jump_fitting_two_ratios_is_ambiguous():
    rows = _rows("ZZA", [100.0, 100.0, 22.5, 22.6])  # 0.225: 4:1 -> -10%, 5:1 -> +12.5% both within 15%
    _, rep = split_guard.guard_series(rows, CFG, None)
    assert rep["gap"].startswith("ambiguous corporate action:") and "4:1 and 5:1" in rep["gap"]


def test_half_configured_block_is_refused():
    with pytest.raises(ValueError):
        split_guard.config({"enabled": True, "split_ratios": [2]})
    assert split_guard.config({"enabled": False}) is None


# ── reader integration ───────────────────────────────────────────────────────────────────────────────────────────
class _Cur:
    def __init__(self, conn):
        self.conn, self.description, self._rows = conn, [], []

    def execute(self, sql, params=None):
        if "FROM market_ohlcv_bars" in sql and "SELECT symbol, bar_time, open, high" in sql:
            cols = ["symbol", "bar_time", "open", "high", "low", "close", "volume", "source", "created_at"]
            want = set(params[1])
            self.description = [(x,) for x in cols]
            self._rows = [tuple(r[x] for x in cols) for r in self.conn.bars if r["symbol"] in want]
        else:
            self.description, self._rows = [], []

    def fetchall(self):
        return self._rows

    def close(self):
        pass


class _Conn:
    def __init__(self, bars):
        self.bars = bars

    def set_session(self, readonly=False):
        pass

    def cursor(self):
        return _Cur(self)

    def close(self):
        pass


def _bars(sym, closes, days):
    return [
        {"symbol": sym, "bar_time": datetime.fromisoformat(d).replace(hour=16, tzinfo=ET), "open": None, "high": None,
         "low": None, "close": cl, "volume": None, "source": "synthetic", "created_at": None}
        for d, cl in zip(days, closes)
    ]


def test_reader_adjusts_split_and_drops_ambiguous_symbol_with_reason():
    days = _days(5)
    conn = _Conn(
        _bars("SPY", [500.0, 505.0, 500.0, 480.0, 485.0], days)
        + _bars("ZZA", [300.0, 306.0, 303.0, 91.0, 93.0], days)
        + _bars("ZZB", [300.0, 303.0, 101.0, 302.0, 301.0], days)
        + _bars("ZZC", [50.0, 51.0, 45.0, 44.0, 45.0], days)
    )
    r = rd.PgReader(lambda: conn, split_guard=CFG_BLOCK)
    end = datetime.fromisoformat(days[-1]).replace(hour=20, tzinfo=ET)
    out = r.daily_bars(["ZZA", "ZZB", "ZZC", "SPY"], sessions=5, end=end)
    by = {}
    for row in out:
        by.setdefault(row["symbol"], []).append(row)
    assert "ZZB" not in by and r.series_gaps["ZZB"].startswith("reverted jump:")
    assert [round(x["close"], 2) for x in by["ZZA"]] == [100.0, 102.0, 101.0, 91.0, 93.0]
    assert r.split_adjustments["ZZA"][0]["ratio"] == "3:1" and r.split_adjustments["ZZA"][0]["peer_move_pct"] == -4.0
    assert [x["close"] for x in by["ZZC"]] == [50.0, 51.0, 45.0, 44.0, 45.0]  # -11.8% day untouched
    assert "ZZC" not in r.series_gaps and "ZZC" not in r.split_adjustments
    assert len(by["SPY"]) == 5
    off = rd.PgReader(lambda: conn, split_guard=False).daily_bars(["ZZA"], sessions=5, end=end)
    assert [x["close"] for x in off] == [300.0, 306.0, 303.0, 91.0, 93.0]


# ── sectors: a group with one gapped member uses the other ───────────────────────────────────────────────────────
class _SectorReader:
    def __init__(self, series, gaps):
        self._series, self.series_gaps, self.split_adjustments = series, gaps, {}

    def daily_bars(self, symbols, *, sessions, end):
        return [row for s in symbols for row in self._series.get(s, [])]


def test_group_with_one_gapped_member_uses_the_other():
    n = 120
    days = _days(n)
    spy = [400.0 * (1 + 0.001 * ((i % 7) - 3)) for i in range(n)]
    zza = [100.0 * (1 + 0.002 * ((i % 5) - 2)) for i in range(n)]
    series = {"SPY": _rows("SPY", spy, days), "ZZA": _rows("ZZA", zza, days)}  # ZZB was dropped by the guard
    reason = "reverted jump: synthetic"
    policy = {"sectors": {"benchmark": "SPY", "z_window_sessions": 60, "groups": [
        {"key": "pair", "label": "Pair", "kind": "theme", "symbols": ["ZZA", "ZZB"]},
        {"key": "solo", "label": "Solo", "kind": "theme", "symbols": ["ZZB"]},
    ]}}
    now = datetime.fromisoformat(days[-1]).replace(hour=20, tzinfo=ET)
    block = sectors.measure(c.EvalContext(now=now, reader=_SectorReader(series, {"ZZB": reason}), policy=policy))
    pair, solo = block["groups"]
    assert pair["state"] != "UNKNOWN" and pair["r5"] == round((zza[-1] / zza[-6] - 1) * 100, 2)
    assert pair["data_gaps"] == {"ZZB": reason} and "ZZB excluded (reverted jump)" in pair["evidence"]
    assert solo["state"] == "UNKNOWN" and solo["reason_unknown"] == f"data gap: ZZB: {reason}"
    assert sectors.heatmap(block)[0]["data_note"] == "ZZB excluded (reverted jump)"


def test_index_symbols_are_exempt():
    cfg = split_guard.config(dict(CFG_BLOCK, exempt_prefixes=["^"], exempt_symbols=["zzx"]))
    assert split_guard.exempt("^VIX", cfg) and split_guard.exempt("ZZX", cfg) and not split_guard.exempt("ZZA", cfg)
    days = _days(4)
    conn = _Conn(_bars("^VIX", [16.0, 17.0, 27.7, 26.0], days))  # +63% day: real, fits 1:1.5 and 1:2
    r = rd.PgReader(lambda: conn, split_guard=dict(CFG_BLOCK, exempt_prefixes=["^"]))
    out = r.daily_bars(["^VIX"], sessions=4, end=datetime.fromisoformat(days[-1]).replace(hour=20, tzinfo=ET))
    assert [x["close"] for x in out] == [16.0, 17.0, 27.7, 26.0] and not r.series_gaps
