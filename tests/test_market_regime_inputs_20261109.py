"""LQ-20261107-1613 — the regime classifier scores market inputs, not the scanner's own selection.

`scan_score_avg` and `gap_volatility_proxy` average `trade_ai_scans`, i.e. the symbols the scanner chose (gappers).
Since the broad scan runs stopped, avg |gap| is above its 3.0 threshold and avg score below 40 on every run by
construction, so they always added +3 high_volatility and +2 risk_off, and the regime became a two-state function
of the VIX bucket (high_volatility 0.62 / risk_off 0.67). These pins: the scan proxies are context, not score;
the VIX term structure the collector already writes is scored; confidence is the margin between the top two
scores; a partial term-structure set is named. Synthetic indicator rows only.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import market_regime_classifier as mrc  # noqa: E402
from test_market_regime_classifier_snapshot_20261031 import FakeConn, _row  # noqa: E402

BASE = [
    _row("scan_breadth_24h", "broad", 80),
    _row("finviz_health", "risk_on", None, "healthy"),
    _row("market_session", "neutral", None, "regular"),
]


@pytest.fixture(autouse=True)
def _session(monkeypatch):
    fake = types.ModuleType("market_session")
    fake.current_market_session = lambda: "regular"
    monkeypatch.setitem(sys.modules, "market_session", fake)


def _snap(rows):
    return mrc.classify(FakeConn(by_snapshot={"S": BASE + rows}, latest="S"))


def _vix(signal, value):
    return [_row("vix_close", signal, value)]


def _term(r9="contango", r3="contango"):
    return [_row("vix9d_vix_ratio", r9, 0.9 if r9 == "contango" else 1.1),
            _row("vix_vix3m_ratio", r3, 0.85 if r3 == "contango" else 1.08)]


def test_scanner_population_proxies_do_not_move_the_regime():
    calm = _vix("normal", 15.2) + _term()
    biased = [_row("scan_score_avg", "bearish", 9.0), _row("gap_volatility_proxy", "high_vol", 7.5)]
    neutral = [_row("scan_score_avg", "neutral", 50.0), _row("gap_volatility_proxy", "neutral", 2.0)]
    a, b = _snap(calm + biased), _snap(calm + neutral)
    assert (a["regime_label"], a["regime_score"], a["confidence"]) == (b["regime_label"], b["regime_score"],
                                                                       b["confidence"])
    # still recorded as context
    assert a["inputs"]["gap_volatility_proxy"] == "high_vol" and a["inputs"]["scan_score_avg"] == "bearish"


def test_the_two_state_trap_is_gone_vix_and_term_structure_decide():
    gappers = [_row("scan_score_avg", "bearish", 9.0), _row("gap_volatility_proxy", "high_vol", 7.5)]
    calm = _snap(_vix("normal", 15.2) + _term() + gappers)
    stress = _snap(_vix("high", 24.0) + _term("inverted", "inverted") + gappers)
    elevated = _snap(_vix("high", 21.0) + _term() + gappers)
    assert calm["regime_label"] not in ("high_volatility", "risk_off")
    assert stress["regime_label"] in ("high_volatility", "risk_off")
    labels_conf = {(s["regime_label"], s["confidence"]) for s in (calm, stress, elevated)}
    assert len(labels_conf) == 3, labels_conf


def test_volatility_state_follows_vix_not_the_gap_proxy():
    rows = [_row("gap_volatility_proxy", "high_vol", 7.5)]
    assert _snap(_vix("normal", 15.2) + _term() + rows)["volatility_state"] == "neutral"
    assert _snap(_vix("extreme", 34.0) + _term() + rows)["volatility_state"] == "high_vol"
    assert _snap(_vix("low", 11.0) + _term() + rows)["volatility_state"] == "low_vol"


def test_trend_is_not_measured_rather_than_a_constant_bearish():
    snap = _snap(_vix("normal", 15.2) + _term() + [_row("scan_score_avg", "bearish", 9.0)])
    assert snap["trend_state"] == "not_measured" and snap["breadth_state"] == "not_measured"


def test_confidence_is_the_margin_not_top_over_total():
    # backwardation with a high VIX: the two stress regimes are close, so confidence is low, not 0.62
    snap = _snap(_vix("high", 24.0) + _term("inverted", "inverted"))
    assert 0 <= snap["confidence"] < 0.5
    assert _snap(_vix("extreme", 40.0) + _term("inverted", "inverted"))["confidence"] > snap["confidence"]


def test_a_partial_term_structure_set_is_named_not_silent():
    snap = _snap(_vix("normal", 15.2))
    assert "no_term_structure" in snap["missing_data"]
    assert snap["stale_data"] is False  # a missing context leg is named, not a stale snapshot
