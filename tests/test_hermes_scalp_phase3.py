"""Dry tests for Phase 3 Hermes scalp agents (Exit Intelligence + Post-Trade Review)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def test_exit_intelligence_analyze_extended_long():
    from hermes_scalp_exit_intelligence import _analyze_position

    pos = {"symbol": "TEST", "price": 55.0, "entry": 45.0, "side": "long", "current_R": 2.5, "stop": 44.0}
    cons = {"target_mean": 50.0, "n_analysts": 5}
    sug = _analyze_position(pos, cons)
    assert sug is not None
    assert sug["suggestion_type"] == "partial_profit_extended_above_street"
    assert sug["price_vs_consensus_pct"] == 10.0


def test_exit_intelligence_stop_over_consensus():
    from hermes_scalp_exit_intelligence import _analyze_position

    pos = {"symbol": "TEST", "price": 53.0, "entry": 45.0, "side": "long", "current_R": 1.0, "stop": 52.0}
    cons = {"target_mean": 50.0, "n_analysts": 8}
    sug = _analyze_position(pos, cons)
    assert sug is not None
    assert sug["suggestion_type"] == "stop_over_consensus"


def test_post_trade_critique_deterministic():
    from hermes_scalp_post_trade_review import _critique_trade, _stop_quality_score

    row = {
        "id": 99,
        "symbol": "NVDA",
        "entry_price": 100.0,
        "exit_price": 102.0,
        "planned_stop": 99.0,
        "max_adverse_excursion": -0.5,   # % from entry (MAE)
        "max_favorable_excursion": 4.0,  # % from entry (MFE) → ~4R at 1% risk
        "breakeven_trigger_r": 1.2,
        "trailing_active": False,
        "market_regime": "trending",
        "initial_stop_atr": 1.2,
    }
    c = _critique_trade(row)
    assert c["symbol"] == "NVDA"
    assert "initial_stop_vs_mae" in c
    assert "trail_activation_correct" in c
    assert c["r_left_on_table"] is not None
    assert 1 <= _stop_quality_score(c) <= 5
    assert len(c["policy_sections_reviewed"]) >= 4


def test_phase3_scripts_once_smoke():
    """Run --once ticks without crashing."""
    import subprocess

    for script in ("hermes_scalp_exit_intelligence.py", "hermes_scalp_post_trade_review.py"):
        r = subprocess.run(
            [str(ROOT / ".venv/bin/python3"), str(ROOT / "scripts" / script), "--once"],
            capture_output=True,
            text=True,
            cwd=str(ROOT),
            timeout=30,
        )
        assert r.returncode == 0, f"{script} failed: {r.stderr}"
        out = json.loads(r.stdout)
        assert isinstance(out, dict)


if __name__ == "__main__":
    test_exit_intelligence_analyze_extended_long()
    test_exit_intelligence_stop_over_consensus()
    test_post_trade_critique_deterministic()
    test_phase3_scripts_once_smoke()
    print("OK: all phase3 tests passed")