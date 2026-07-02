"""Tests for momentum scalp regime detection + regime stoplight."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "scripts" / "lib"
sys.path.insert(0, str(LIB))


def _load(name, fname):
    spec = importlib.util.spec_from_file_location(name, LIB / fname)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_strong_trending_bull():
    reg = _load("momentum_scalp_regime", "momentum_scalp_regime.py")
    ctx = {"rvol": 2.1, "adx": 28, "sma20_pct": 2, "sma50_pct": 4, "direction": "long"}
    out = reg.score_regime(ctx)
    assert out["regime"] == "strong_trending_bull"
    assert out["confidence"] >= 50


def test_ranging_low_vol():
    reg = _load("momentum_scalp_regime", "momentum_scalp_regime.py")
    ctx = {"rvol": 0.9, "adx": 15, "sma20_pct": 0.5, "sma50_pct": -0.5, "direction": "long"}
    out = reg.score_regime(ctx)
    assert out["regime"] == "ranging"


def test_regime_stoplight_tighter_in_ranging():
    sl = _load("stoplight_regime_thresholds", "stoplight_regime_thresholds.py")
    trend = sl.evaluate_regime_stoplight(regime="trending", dist_r=0.25, dist_pct=None, dist_atr=None, modifiers={})
    range_ = sl.evaluate_regime_stoplight(regime="ranging", dist_r=0.25, dist_pct=None, dist_atr=None, modifiers={})
    assert sl.LEVEL_RANK.get(trend["alert_level"], 0) <= sl.LEVEL_RANK.get(range_["alert_level"], 0)


def test_regime_shift_suggestion():
    sl = _load("stoplight_regime_thresholds", "stoplight_regime_thresholds.py")
    out = sl.evaluate_regime_stoplight(
        regime="regime_shift",
        regime_meta={"regime_shift_detected": True, "regime_shift_direction": "trending → ranging"},
        dist_r=1.0,
        dist_pct=10,
        dist_atr=3,
        modifiers={},
    )
    assert out["alert_level"] in ("amber", "yellow", "red")
    assert any("Layer 4" in s for s in out["policy_suggestions"])


if __name__ == "__main__":
    test_strong_trending_bull()
    test_ranging_low_vol()
    test_regime_stoplight_tighter_in_ranging()
    test_regime_shift_suggestion()
    print("OK — momentum_scalp_regime tests passed")