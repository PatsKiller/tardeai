#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import pytest  # noqa: E402
import watchlist_volatility as wv  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_atr20(tmp_path, monkeypatch):
    """Keep these tests off the network and off the shared runtime cache.

    Found 2026-09-07 by the m2-canary-20260907 I-2 differential.
    `attach_atr20_batch` calls `_fetch_atr20`, which imports
    `watchlist_entry_planner._bars` and makes a LIVE yfinance/Alpaca request, and
    it reads/writes the shared `data/runtime/atr20_cache.json` inside the working
    tree. So the result depended on two things that have nothing to do with the
    behaviour under test: whether the network answered, and what earlier runs had
    left in the cache (17KB in one worktree, 5KB in another).

    That made `test_attach_atr20_prioritizes_plans` order-dependent — it passed in
    the baseline full-suite ordering and failed alone, in BOTH trees. Adding four
    test files to the suite was enough to flip it, which briefly looked like an
    integration regression and was not.

    The test asserts prioritisation and fetch-budget behaviour. Neither needs a
    provider. Pin the cache to tmp_path and make the fetch deterministic.
    """
    monkeypatch.setattr(wv, "ATR20_CACHE_PATH", tmp_path / "atr20_cache.json")
    calls: list[str] = []

    def _stub_fetch(symbol: str):
        calls.append(symbol.upper())
        return 1.25

    monkeypatch.setattr(wv, "_fetch_atr20", _stub_fetch)
    yield calls


def test_mrln_plan_stop_context():
    out = wv.plan_volatility_fields(
        entry_limit=4.35, entry_stop=3.90, price=4.35, atr_14=0.71,
        atr_20=0.57, atr_20_pct=13.1,
    )
    assert out["plan_stop_dist_pct"] == 10.34
    assert out["plan_stop_atr_mult"] < 1.0
    assert out["plan_stop_atr20_mult"] < 1.0
    assert out["plan_stop_tight"] is True
    assert out["volatility_band_20"] == "extreme"


def test_agilent_style_plan():
    out = wv.plan_volatility_fields(
        entry_limit=125.75, entry_stop=120.50, price=133.63,
        atr_14=3.92, atr_20=3.85, atr_20_pct=2.88,
    )
    assert out["plan_stop_dist_pct"] == 4.17
    assert out["plan_stop_atr20_mult"] > 1.0
    assert out["plan_stop_tight"] is False
    assert out["volatility_band_20"] == "moderate"


def test_volatility_bands():
    assert wv.volatility_band(1.5) == "low"
    assert wv.volatility_band(4) == "moderate"
    assert wv.volatility_band(8) == "high"
    assert wv.volatility_band(13) == "extreme"


def test_atr_from_bars():
    bars = [{"high": 10, "low": 9, "close": 9.5}] * 25
    assert wv._atr_from_bars(bars, 20) == 1.0


def test_attach_atr20_prioritizes_plans():
    items = [
        {"symbol": "ZZZ", "price": 10.0},
        {"symbol": "AAA", "price": 20.0, "entry_stop": 18.0, "entry_limit": 21.0, "hermes_rank": 500},
        {"symbol": "BBB", "price": 30.0, "entry_stop": 27.0, "entry_limit": 31.0, "hermes_rank": 10},
    ]
    wv.attach_atr20_batch(items, max_fetch=1)
    plan_hits = sum(1 for it in items if it.get("entry_stop") and it.get("atr_20") is not None)
    assert plan_hits == 1
    assert items[1].get("atr_20") is not None or items[2].get("atr_20") is not None