"""Tests for stop vs consensus target monitoring."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))


def _load():
    spec = importlib.util.spec_from_file_location(
        "stop_consensus_check", ROOT / "scripts" / "lib" / "stop_consensus_check.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stop_above_mean_detected():
    mod = _load()
    hit = mod.check_stop_over_consensus(
        "SMCI", 30.40, 35.00,
        {"target_mean": 27.00, "n_analysts": 16, "source": "test"},
    )
    assert hit is not None
    assert hit["consensus_gap_pct"] > 0


def test_stop_below_mean_ok():
    mod = _load()
    hit = mod.check_stop_over_consensus(
        "AAPL", 150.0, 200.0,
        {"target_mean": 220.0, "n_analysts": 30, "source": "test"},
    )
    assert hit is None


def test_trailing_trigger_math():
    mod = _load()
    assert mod.trailing_trigger(100.0, 5.0) == 95.0


def test_stop_vs_consensus_pct_signed():
    mod = _load()
    assert mod.stop_vs_consensus_pct(30.0, 27.0) == round(100 * 3 / 27, 2)
    assert mod.stop_vs_consensus_pct(22.6, 24.9) < 0
    assert mod.stop_vs_consensus_pct(None, 24.9) is None


def test_price_vs_consensus_pct():
    mod = _load()
    assert mod.price_vs_consensus_pct(62.45, 94.5) < 0
    assert mod.price_vs_consensus_pct(410.0, 398.83) > 0


if __name__ == "__main__":
    test_stop_above_mean_detected()
    test_stop_below_mean_ok()
    test_trailing_trigger_math()
    print("OK — stop_over_consensus tests passed")