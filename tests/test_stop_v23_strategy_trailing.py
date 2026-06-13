"""Tests for STOP-V2.3 strategy trailing tiers."""
import subprocess, sys, os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))


def test_policy_compiles():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/scripts/strategy_trailing_policy.py"]).returncode == 0


def test_momentum_tighter_than_income():
    from strategy_trailing_policy import get_trailing_policy
    m = get_trailing_policy("momentum_scalp")
    i = get_trailing_policy("dividend_growth_compounder")
    # Momentum first tier at 1.0R, income at 1.5R
    assert m["tiers"][0][0] < i["tiers"][0][0]


def test_swing_medium_tiers():
    from strategy_trailing_policy import get_trailing_policy
    s = get_trailing_policy("swing_trade")
    assert s["family"] == "swing"
    assert s["tiers"][0][0] == 1.0  # breakeven at 1.0R


def test_income_wider_tiers():
    from strategy_trailing_policy import get_trailing_policy
    i = get_trailing_policy("reit_income")
    assert i["family"] == "income"
    assert i["tiers"][0][0] == 1.5  # breakeven at 1.5R (wider than momentum)


def test_position_no_auto_tighten_default():
    from strategy_trailing_policy import get_trailing_policy
    p = get_trailing_policy("core_growth_compounder")
    assert p["family"] == "position"
    assert p["tiers"][0][0] == 2.0  # breakeven only at 2.0R (very wide)


def test_unknown_requires_review():
    from strategy_trailing_policy import get_trailing_policy
    u = get_trailing_policy("some_unknown_strategy")
    assert u["requires_review"] is True
    assert len(u["tiers"]) == 0


def test_recommend_hold_below_threshold():
    from strategy_trailing_policy import recommend_stop
    r = recommend_stop("momentum_scalp", 10.0, 9.5, 9.5, 10.3, market_hours=True)
    assert r["action"] == "hold"  # R=0.6, below 1.0R threshold


def test_recommend_trail_at_threshold():
    from strategy_trailing_policy import recommend_stop
    r = recommend_stop("momentum_scalp", 10.0, 9.5, 9.5, 10.5, market_hours=True)
    assert r["action"] == "recommend_trail"  # R=1.0, breakeven tier
    assert r["recommended_stop"] == 10.0  # breakeven = entry


def test_after_hours_blocks_trailing():
    from strategy_trailing_policy import recommend_stop
    r = recommend_stop("momentum_scalp", 10.0, 9.5, 9.5, 10.5, market_hours=False)
    assert r["action"] == "recommend_deferred"
    assert r["blocked_by"] == "after_hours"


def test_stop_never_weakens():
    from strategy_trailing_policy import recommend_stop
    # Current stop at $10.50, recommendation would be breakeven at $10.0 — should hold
    r = recommend_stop("momentum_scalp", 10.0, 9.5, 10.5, 10.5, market_hours=True)
    assert r["action"] == "hold"
    assert r["recommended_stop"] == 10.5  # keeps current (higher) stop


def test_no_orders_in_policy():
    src = open(f"{PROJECT_ROOT}/scripts/strategy_trailing_policy.py").read()
    assert "submit_order" not in src
    assert "cancel_order" not in src
    assert "replace_order" not in src


def test_v22_compiles():
    assert subprocess.run([PY, "-m", "py_compile",
        f"{PROJECT_ROOT}/scripts/unified_stop_supervisor.py"]).returncode == 0


# ── STOP-V2.4 hybrid structural overlay (config-gated) ───────────────────────────────────────────

def test_v24_overlay_default_off_is_noop():
    """With config disabled (default), passing symbol must NOT add a hybrid key or change the stop."""
    import strategy_trailing_policy as p
    p._HYBRID_CFG_CACHE = {"enabled": False}
    r = p.recommend_stop("swing_breakout", 100.0, 95.0, 95.0, 110.0, market_hours=True, symbol="V")
    assert "hybrid" not in r
    assert r["recommended_stop"] == 105.0  # pure R-multiple lock 1.0R


def test_v24_overlay_only_tightens():
    """The overlay can only RAISE the stop above the R-multiple baseline, never lower it."""
    import strategy_trailing_policy as p
    # synthetic levels: chandelier/ma far BELOW baseline → overlay must be a no-op (not loosen)
    p._HYBRID_CFG_CACHE = {"enabled": True, "atr_period": 14, "chandelier_lookback": 22,
                           "adx_ranging_below": 20, "adx_trending_above": 25, "ma_proximity_atr": 1.5,
                           "families": {"swing": {"chandelier": True, "base_atr_mult": 3.0}}}
    p._structural_levels = lambda sym, cfg: {"atr": 1.0, "ema20": 50.0, "sma50": 50.0,
                                             "adx": 30.0, "highest_high": 90.0, "close": 110.0}
    r = p.recommend_stop("swing_breakout", 100.0, 95.0, 95.0, 110.0, market_hours=True, symbol="ZZ")
    # baseline lock 1R = 105; chandelier = 90-3 = 87 (below) → must stay 105, never drop
    assert r["recommended_stop"] >= 105.0
    p._HYBRID_CFG_CACHE = {"enabled": False}  # reset for other tests


def test_v24_overlay_no_orders():
    src = open(f"{PROJECT_ROOT}/scripts/strategy_trailing_policy.py").read()
    for sym in ("submit_order", "cancel_order", "replace_order", "place_order"):
        assert sym not in src
