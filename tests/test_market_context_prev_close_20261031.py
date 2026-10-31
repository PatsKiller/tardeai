"""Market header previous close comes from the daily bars, not meta.chartPreviousClose.

Live verification 2026-10-31 (agent_scratch/live-verify/MATRIX.md, #2318 row): Yahoo's ``chartPreviousClose`` is the
close BEFORE THE FIRST BAR OF THE REQUESTED RANGE. With range=2d the header compared against the close two sessions
back: SPY "prev close $772.31" (the 10-28 close) on Saturday 10-31, real last close 755.72; an in-session change of
-2.15% where Yahoo published -1.773%. The fixtures below are shaped like Yahoo's real range=2d/5d responses (values
from the live 2026-10-31 fetch). Hermetic: requests stubbed, clock and session forced, no network.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_context as mc  # noqa: E402

# Daily bars as Yahoo returns them: timestamps at the 09:30 ET open (13:30Z in EDT).
BARS_5D = {
    "timestamp": [1793022600, 1793109000, 1793195400, 1793281800, 1793368200],  # 10-26 .. 10-30
    "close": [765.37, 769.66, 772.31, 769.36, 755.72],
}


def _result(meta, bars):
    return {
        "meta": meta,
        "timestamp": bars["timestamp"],
        "indicators": {"quote": [{"close": bars["close"]}]},
    }


class _Resp:
    def __init__(self, result):
        self.status_code = 200
        self._result = result

    def json(self):
        return {"chart": {"result": [self._result]}}


def _fetch(monkeypatch, meta, bars, session, now):
    monkeypatch.setattr(mc.requests, "get", lambda *a, **k: _Resp(_result(meta, bars)))
    monkeypatch.setattr(mc, "_current_session", lambda now=None: session)
    monkeypatch.setattr(mc, "_now_utc", lambda: now)
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    return mc._fetch_yahoo(["SPY"])["SPY"]


def test_weekend_header_shows_the_last_close_not_two_sessions_back(monkeypatch):
    # Saturday 2026-10-31: closed. range=2d would have said chartPreviousClose 772.31 (10-28).
    meta = {"regularMarketPrice": 755.72, "chartPreviousClose": 772.31}
    bars = {"timestamp": BARS_5D["timestamp"][-2:], "close": BARS_5D["close"][-2:]}
    q = _fetch(monkeypatch, meta, bars, "closed", datetime(2026, 10, 31, 14, 0, tzinfo=timezone.utc))
    assert q["prev_close"] == 755.72
    assert q["price_is_stale"] is True and q["change_percent"] == 0.0


def test_regular_session_change_is_against_yesterdays_close(monkeypatch):
    # Friday 10-30 15:00 ET, regular session: today's bar is in progress; reference is the 10-29 close 769.36.
    meta = {"regularMarketPrice": 755.72, "chartPreviousClose": 772.31, "regularMarketChangePercent": -1.773}
    bars = {"timestamp": BARS_5D["timestamp"][-2:], "close": BARS_5D["close"][-2:]}
    q = _fetch(monkeypatch, meta, bars, "regular", datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc))
    assert q["prev_close"] == 769.36
    assert q["change_percent"] == pytest.approx(-1.77, abs=0.01)  # matches Yahoo's own -1.773, not -2.15


def test_premarket_compares_against_the_last_completed_close(monkeypatch):
    # Monday 11-02 07:00 ET (EST, 12:00Z): no bar for today yet; reference is Friday's 755.72.
    meta = {"regularMarketPrice": 755.72, "chartPreviousClose": 765.37, "preMarketPrice": 740.6}
    q = _fetch(monkeypatch, meta, BARS_5D, "premarket", datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc))
    assert q["prev_close"] == 755.72
    assert q["change_percent"] == pytest.approx(-2.0, abs=0.01)


def test_no_bars_falls_back_to_meta(monkeypatch):
    meta = {"regularMarketPrice": 765.0, "chartPreviousClose": 762.76}
    q = _fetch(
        monkeypatch, meta, {"timestamp": [], "close": []}, "regular", datetime(2026, 10, 30, 19, tzinfo=timezone.utc)
    )
    assert q["prev_close"] == 762.76


def test_the_request_asks_for_more_than_two_sessions(monkeypatch):
    seen = {}

    def _get(url, headers=None, params=None, timeout=None):
        seen.update(params or {})
        return _Resp(_result({"regularMarketPrice": 755.72}, BARS_5D))

    monkeypatch.setattr(mc.requests, "get", _get)
    monkeypatch.setattr(mc, "_current_session", lambda now=None: "closed")
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    mc._fetch_yahoo(["SPY"])
    assert seen.get("range") == "5d"
