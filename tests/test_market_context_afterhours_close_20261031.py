"""After hours, a symbol with no after-hours print shows TODAY's close, not yesterday's.

Live 2026-10-31: the Home header VIX read 17.2 all weekend. Source: the 10-30 17:30 orchestrator run, whose
market_context fetch ran in the after-hours session; ^VIX has no postMarketPrice, so the price fell through to the
previous close -- the 10-29 close, 17.20 -- while VIX had closed 10-30 at 19.42 (Yahoo daily bars, fetched 2026-10-31).
The fixtures are shaped like Yahoo's range=5d response with those real closes. Hermetic: requests stubbed, clock and
session forced, no network.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_context as mc  # noqa: E402

# ^VIX daily bars 10-26 .. 10-30 (timestamps at the 09:30 ET open, 13:30Z in EDT).
VIX_BARS = {
    "timestamp": [1793022600, 1793109000, 1793195400, 1793281800, 1793368200],
    "close": [18.39, 17.52, 16.91, 17.20, 19.42],
}
FRI_1739_ET = datetime(2026, 10, 30, 21, 39, tzinfo=timezone.utc)  # the 10-30 17:30 run's market_context fetch


class _Resp:
    status_code = 200

    def __init__(self, meta):
        self._r = {
            "meta": meta,
            "timestamp": VIX_BARS["timestamp"],
            "indicators": {"quote": [{"close": VIX_BARS["close"]}]},
        }

    def json(self):
        return {"chart": {"result": [self._r]}}


def _fetch(monkeypatch, meta, session="afterhours", now=FRI_1739_ET, sym="VIX"):
    monkeypatch.setattr(mc.requests, "get", lambda *a, **k: _Resp(meta))
    monkeypatch.setattr(mc, "_current_session", lambda now=None: session)
    monkeypatch.setattr(mc, "_now_utc", lambda: now)
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    return mc._fetch_yahoo([sym])[sym]


def test_afterhours_vix_without_post_print_is_todays_close_not_yesterdays(monkeypatch):
    q = _fetch(monkeypatch, {"regularMarketPrice": 19.42, "postMarketPrice": None})
    assert q["price"] == 19.42  # was 17.2 (the 10-29 close)
    assert q["prev_close"] == 17.2
    assert q["price_field"] == "regularMarketPrice"
    assert q["price_is_stale"] is False
    assert q["change_percent"] == pytest.approx(12.91, abs=0.01)


def test_afterhours_post_print_still_wins(monkeypatch):
    q = _fetch(monkeypatch, {"regularMarketPrice": 755.72, "postMarketPrice": 754.10}, sym="SPY")
    assert q["price"] == 754.10 and q["price_field"] == "postMarketPrice"


def test_afterhours_with_no_price_at_all_is_still_labelled_stale(monkeypatch):
    q = _fetch(monkeypatch, {"regularMarketPrice": None, "postMarketPrice": None})
    assert q["price_is_stale"] is True and q["price_field"] == "previousClose"
    assert q["change_percent"] == 0.0


def test_get_market_snapshot_vix_after_hours_is_todays_close(monkeypatch):
    monkeypatch.setattr(
        mc,
        "_round_robin_fetch",
        lambda syms: {
            s: (
                _fetch(monkeypatch, {"regularMarketPrice": 19.42})
                if s == "VIX"
                else {"symbol": s, "price": 1.0, "change_percent": 0.0, "source": "yahoo"}
            )
            for s in syms
        },
    )
    snap = mc.get_market_snapshot()
    assert snap["vix"]["price"] == 19.42 and snap["vix"]["price_is_stale"] is False
