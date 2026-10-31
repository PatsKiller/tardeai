"""Market header honesty (DSN-20261031-market-risk-engine-P0-T9).

RCA finding 10: the scalp header printed "SPY +29.30%" on 2026-10-27 (a real +0.29% day) because
scripts/market_context.py multiplied Yahoo's already-percent change by 100 for any value under 1.0; and the 04:00/07:00
pre-open briefs printed "+0.00%" against a previous close all morning on 2026-10-30, so a stale quote read as a flat
live one. Pins: change% is derived from the session's two prices (0.29, not 29.3); a session without a print is
price_is_stale with change 0.0 and renders as "prev close"; a move beyond config/market_context_policy.json is
implausible and renders as n/a; both renderers (brief header, scalp header) honour the flags. Hermetic: requests
stubbed, session forced, no network.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import market_context as mc  # noqa: E402


class _Resp:
    def __init__(self, meta):
        self.status_code = 200
        self._meta = meta

    def json(self):
        return {"chart": {"result": [{"meta": self._meta}]}}


def _fetch(monkeypatch, meta, session):
    monkeypatch.setattr(mc.requests, "get", lambda *a, **k: _Resp(meta))
    monkeypatch.setattr(mc, "_current_session", lambda now=None: session)
    monkeypatch.setattr(mc.time, "sleep", lambda s: None)
    return mc._fetch_yahoo(["SPY"])["SPY"]


def test_policy_carries_the_bounds():
    pol = mc.market_context_policy()
    for k in ("max_plausible_index_move_pct", "max_plausible_sector_move_pct", "max_plausible_vix_move_pct"):
        assert k in pol, k


def test_a_real_quarter_percent_day_is_not_twenty_nine_percent(monkeypatch):
    q = _fetch(
        monkeypatch,
        {"regularMarketPrice": 765.0, "chartPreviousClose": 762.76, "regularMarketChangePercent": 0.293},
        "regular",
    )
    assert q["change_percent"] == pytest.approx(0.29, abs=0.01)
    assert q["price_is_stale"] is False and q["implausible"] is False and q["price_field"] == "regularMarketPrice"


def test_premarket_without_a_print_is_stale_not_flat(monkeypatch):
    q = _fetch(
        monkeypatch, {"regularMarketPrice": 763.96, "chartPreviousClose": 763.96, "preMarketPrice": None}, "premarket"
    )
    assert q["price_is_stale"] is True and q["price_field"] == "previousClose"
    assert q["change_percent"] == 0.0 and q["price"] == 763.96


def test_premarket_with_a_print_derives_the_change_from_prices(monkeypatch):
    q = _fetch(
        monkeypatch,
        {
            "regularMarketPrice": 766.42,
            "chartPreviousClose": 766.42,
            "preMarketPrice": 751.1,
            "preMarketChangePercent": -2.0,
        },
        "premarket",
    )
    assert q["price_is_stale"] is False and q["change_percent"] == pytest.approx(-2.0, abs=0.01)


def test_an_implausible_move_is_flagged(monkeypatch):
    q = _fetch(monkeypatch, {"regularMarketPrice": 150.0, "chartPreviousClose": 100.0}, "regular")
    assert q["implausible"] is True and q["change_percent"] == pytest.approx(50.0)


def test_snapshot_passes_the_flags_through(monkeypatch):
    raw = {
        "SPY": {
            "price": 763.96,
            "change_percent": 0.0,
            "prev_close": 763.96,
            "source": "yahoo",
            "price_is_stale": True,
            "price_field": "previousClose",
            "session": "premarket",
        },
        "QQQ": {"price": 150.0, "change_percent": 50.0, "prev_close": 100.0, "source": "yahoo", "implausible": True},
        "IWM": {"price": 0, "change_percent": 0, "source": "unavailable"},
        "VIX": {"price": 18.4, "change_percent": 0.0, "source": "yahoo", "price_is_stale": True},
    }
    monkeypatch.setattr(
        mc,
        "_round_robin_fetch",
        lambda syms: {s: raw.get(s, {"price": 1, "change_percent": 0.1, "source": "yahoo"}) for s in syms},
    )
    snap = mc.get_market_snapshot()
    assert snap["indices"]["SPY"]["price_is_stale"] is True and snap["indices"]["SPY"]["session"] == "premarket"
    assert snap["indices"]["QQQ"]["implausible"] is True
    assert snap["indices"]["IWM"]["price_is_stale"] is True, "unavailable source is stale by definition"
    assert snap["vix"]["price_is_stale"] is True


def _snapshot(spy, vix):
    return {
        "indices": {"SPY": spy, "QQQ": dict(spy), "IWM": dict(spy)},
        "vix": vix,
        "sectors": [],
        "breadth_label": "Neutral",
    }


def test_brief_header_says_prev_close_and_n_a_instead_of_numbers():
    import telegram_alert as ta

    stale = {"price": 763.96, "change_percent": 0.0, "price_is_stale": True, "session": "premarket"}
    text = ta.build_telegram_message(
        [],
        {},
        "0400",
        "2026-10-30",
        market_snapshot=_snapshot(
            stale, {"price": 18.4, "change_percent": 0.0, "direction": "flat", "price_is_stale": True}
        ),
    )
    assert "prev close $763.96" in text and "+0.00%" not in text and "no premarket print yet" in text
    assert "VIX* 18.4" in text and "prev close · no live print yet" in text
    bad = {"price": 150.0, "change_percent": 50.0, "implausible": True}
    text2 = ta.build_telegram_message(
        [],
        {},
        "0930",
        "2026-10-30",
        market_snapshot=_snapshot(bad, {"price": 20.0, "change_percent": 10.0, "direction": "spiking"}),
    )
    assert "n/a (quote failed plausibility)" in text2 and "+50.00%" not in text2
    live = {"price": 756.09, "change_percent": -1.35, "price_is_stale": False}
    text3 = ta.build_telegram_message(
        [],
        {},
        "1600",
        "2026-10-30",
        market_snapshot=_snapshot(live, {"price": 19.4, "change_percent": 12.9, "direction": "spiking"}),
    )
    assert "🔴 *SPY* -1.35% $756.09" in text3


def test_scalp_header_honours_the_flags():
    import continuous_runner as cr

    stale = _snapshot(
        {"price": 763.96, "change_percent": 0.0, "price_is_stale": True}, {"price": 18.4, "price_is_stale": True}
    )
    assert "SPY prev close 763.96  VIX 18.4 (prev close)" in cr._build_live_alert([], "04:08", stale)
    bad = _snapshot({"price": 1.0, "change_percent": 29.3, "implausible": True}, {"price": 17.9, "implausible": True})
    assert "SPY n/a  VIX n/a" in cr._build_live_alert([], "09:34", bad)
    live = _snapshot({"price": 765.0, "change_percent": 0.29}, {"price": 17.9})
    assert "SPY +0.29%  VIX 17.9" in cr._build_live_alert([], "09:34", live)
