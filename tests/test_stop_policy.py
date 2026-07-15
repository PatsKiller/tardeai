#!/usr/bin/env python3
"""Dynamic stop-policy tier regression gates (2026-07-14).

Guards config/stop_policy.yaml + scripts/holding_family.py tier resolution:
asset-type-driven bands, operator pins, lifecycle tightening, legacy fallback,
portfolio drawdown guard math — all advisory; no broker imports anywhere here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import holding_family as hf  # noqa: E402

POLICY_PATH = ROOT / "config" / "stop_policy.yaml"


def test_policy_file_loads_and_is_enabled():
    pol = hf._policy()
    assert pol.get("enabled") is True
    assert pol.get("version")
    tiers = hf.policy_tiers()
    for t in ("income_defensive", "growth_tech", "sector_tactical",
              "stock_core", "stock_tactical",
              "momentum", "swing", "income", "position"):
        assert t in tiers, f"tier {t} missing"


def test_tier_bands_match_operator_spec():
    """The bands John specified: income 5-8/6-8, growth 8-12/10-12,
    sector ETF 6-10/7-10, stock core 7-10/8-10, stock tactical 4-7/5-7."""
    spec = {
        "income_defensive": (5.0, 8.0, 6.0, 8.0),
        "growth_tech": (8.0, 12.0, 10.0, 12.0),
        "sector_tactical": (6.0, 10.0, 7.0, 10.0),
        "stock_core": (7.0, 10.0, 8.0, 10.0),
        "stock_tactical": (4.0, 7.0, 5.0, 7.0),
    }
    for fam, (smin, smax, tmin, tmax) in spec.items():
        b = hf.protection_bounds(fam)
        assert (b["stop_min_pct"], b["stop_max_pct"]) == (smin, smax), fam
        assert (b["trail_min_pct"], b["trail_max_pct"]) == (tmin, tmax), fam


def test_legacy_bands_unchanged():
    """Legacy scalp/momentum lanes keep their exact historical bands."""
    legacy = {"momentum": (2.0, 6.0), "swing": (3.0, 8.0),
              "income": (4.0, 10.0), "position": (5.0, 12.0)}
    for fam, (smin, smax) in legacy.items():
        b = hf.protection_bounds(fam)
        assert (b["stop_min_pct"], b["stop_max_pct"]) == (smin, smax), fam


def test_resolution_order():
    """symbol pin beats bucket beats asset_class beats volatility beats default."""
    fam, src = hf.classify_family("JEPQ", atr_pct=1.0)   # covered_call bucket but pinned
    assert fam == "growth_tech" and "override" in src
    fam, src = hf.classify_family("JEPI", atr_pct=1.0)   # dividend_income bucket
    assert fam == "income_defensive" and "bucket" in src
    fam, src = hf.classify_family("XLI", atr_pct=2.0)    # sector_etf asset class
    assert fam == "sector_tactical" and "asset_class" in src
    fam, src = hf.classify_family("AVAV", atr_pct=6.0)   # swing_trade bucket
    assert fam == "stock_tactical"


def test_low_vol_stock_is_stock_core_not_position():
    """A low-ATR individual stock lands in the 7-10% stock_core band, not the
    generic 5-12% position band (the type-specific rule beats the vol map)."""
    fam, src = hf.classify_family("LMT", atr_pct=2.0)
    assert fam == "stock_core", (fam, src)
    fam, _ = hf.classify_family("V", atr_pct=1.8)
    assert fam == "stock_core"


def test_mutual_fund_goes_to_default_tier():
    fam, src = hf.classify_family("FCNTX", atr_pct=None)
    assert fam == hf._policy().get("default_tier", "position")
    assert "default" in src


def test_lifecycle_tightening_never_exits_band():
    """watch/trim shrink stop_max toward the tight end but never below
    stop_min + 0.5 and never widen."""
    base = hf.protection_bounds("growth_tech")
    watch = hf.protection_bounds("growth_tech", lifecycle_stage="watch")
    trim = hf.protection_bounds("growth_tech", lifecycle_stage="trim_candidate")
    assert watch["stop_max_pct"] == base["stop_max_pct"] - 1.0
    assert trim["stop_max_pct"] == base["stop_max_pct"] - 2.0
    assert trim["stop_max_pct"] >= trim["stop_min_pct"] + 0.5
    healthy = hf.protection_bounds("growth_tech", lifecycle_stage="healthy")
    assert healthy["stop_max_pct"] == base["stop_max_pct"]
    # narrow band: shrink clamps at the floor instead of inverting the band
    tight = hf.protection_bounds("stock_tactical", lifecycle_stage="trim_candidate")
    assert tight["stop_max_pct"] >= tight["stop_min_pct"] + 0.5


def test_trail_threshold_per_tier():
    assert hf.trail_pnl_threshold("income_defensive") == 20.0
    assert hf.trail_pnl_threshold("income") == 20.0
    assert hf.trail_pnl_threshold("growth_tech") == 9.0
    assert hf.trail_pnl_threshold("no_such_tier") == hf.TRAIL_PNL_PCT_NORMAL


def test_unknown_family_falls_back_safely():
    b = hf.protection_bounds("no_such_tier")
    assert b["stop_min_pct"] > 0 and b["stop_max_pct"] >= b["stop_min_pct"]


def test_legacy_fallback_without_yaml(tmp_path=None):
    """With the yaml unreadable, the engine must serve the built-in legacy bands
    (backward compatibility guarantee)."""
    saved_cache, saved_path = hf._POLICY_CACHE, hf._POLICY_PATH
    try:
        hf._POLICY_PATH = Path("/nonexistent/stop_policy.yaml")
        hf._POLICY_CACHE = None
        assert hf._policy() == {}
        fam, _ = hf.classify_family("JEPI", atr_pct=1.0)
        assert fam in hf.FAMILY_PROTECTION
        b = hf.protection_bounds("income")
        assert (b["stop_min_pct"], b["stop_max_pct"]) == (4.0, 10.0)
    finally:
        hf._POLICY_CACHE, hf._POLICY_PATH = saved_cache, saved_path


def test_drawdown_guard_config_and_math():
    g = hf._policy().get("portfolio_drawdown_guard") or {}
    assert g.get("enabled") is True
    assert 8.0 <= float(g["alert_pct"]) <= 12.0
    assert float(g["critical_pct"]) > float(g["alert_pct"])
    # math: 1.2M peak, 1.05M now → 12.5% → critical
    peak, cur = 1_200_000.0, 1_050_000.0
    dd = (peak - cur) / peak * 100
    assert dd >= float(g["critical_pct"])


def test_l3_hybrid_trailing_stays_off():
    """Triple-confirmed backtest verdict: the policy file must not re-enable
    hybrid/Layer-3 trailing."""
    txt = POLICY_PATH.read_text()
    assert "hybrid" not in txt.lower().replace("l3 hybrid trailing stays off", "")
    import yaml
    pol = yaml.safe_load(txt)
    assert "hybrid_trailing" not in pol and "layer3" not in pol


def test_no_broker_imports_in_policy_engine():
    """The tier engine and guard are advisory: no broker/order modules imported."""
    for rel in ("scripts/holding_family.py", "scripts/stop_health_check.py"):
        src = (ROOT / rel).read_text()
        for bad in ("schwab_transport", "schwab_order", "place_order",
                    "submit_order", "alpaca_stop_manager"):
            assert bad not in src, f"{bad} referenced in {rel}"


def test_advisor_lifecycle_wiring():
    src = (ROOT / "scripts" / "holding_protection_advisor.py").read_text()
    assert "_lifecycle_stage(" in src
    assert "lifecycle_stage=_stage" in src
    assert "load_holdings_lifecycle_state" in src


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v(); print("OK", k)
    print("ALL PASSED")
