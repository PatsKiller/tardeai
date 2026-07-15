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
    """pin > bucket > dynamic vol tier > asset_class > type/ATR fallback > default."""
    fam, src = hf.classify_family("JEPI", atr_pct=1.0)   # dividend_income bucket wins
    assert fam == "income_defensive" and "bucket" in src
    fam, src = hf.classify_family("JEPQ", atr_pct=1.0)   # no pin: dynamic beta 0.83
    assert fam == "vol_medium" and src.startswith("vol_tier:medium"), (fam, src)
    fam, src = hf.classify_family("XLI", atr_pct=2.0)    # vol tier beats asset_class now
    assert fam == "vol_medium" and "vol_tier" in src
    fam, src = hf.classify_family("AVAV", atr_pct=6.0)   # swing_trade bucket
    assert fam == "stock_tactical"


def test_low_vol_stock_fallback_without_vol_data():
    """With NO beta/vol data available, a low-ATR individual stock still lands in
    stock_core (7-10%), not the generic 5-12% position band."""
    saved_v, saved_e = hf._VOLTIER_PATH, hf._ENRICH_PATH
    try:
        hf._VOLTIER_PATH = Path("/nonexistent/vt.json")
        hf._ENRICH_PATH = Path("/nonexistent/ec.json")
        fam, src = hf.classify_family("LMT", atr_pct=2.0)
        assert fam == "stock_core", (fam, src)
        fam, _ = hf.classify_family("V", atr_pct=1.8)
        assert fam == "stock_core"
    finally:
        hf._VOLTIER_PATH, hf._ENRICH_PATH = saved_v, saved_e


def test_low_vol_stock_with_data_uses_vol_tier():
    """WITH beta data, dynamic classification wins (LMT beta 0.12 -> vol_low)."""
    fam, src = hf.classify_family("LMT", atr_pct=2.0)
    assert fam == "vol_low" and "vol_tier" in src, (fam, src)


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


def test_vol_tier_bands_match_operator_spec():
    """Dynamic spec (2026-07-14.2): low 6-8 trail, medium 9-11, high 10-13."""
    spec = {"vol_low": (6.0, 8.0), "vol_medium": (9.0, 11.0), "vol_high": (10.0, 13.0)}
    for fam, (tmin, tmax) in spec.items():
        b = hf.protection_bounds(fam)
        assert (b["trail_min_pct"], b["trail_max_pct"]) == (tmin, tmax), fam


def test_classify_volatility_tier_rules():
    """Pure-function rules: beta cutoffs, income-yield defensive, sector escalation."""
    f = hf.classify_volatility_tier
    assert f(0.25, None) == "low"                      # BND-style outright low beta
    assert f(0.7, None, div_yield_pct=3.25) == "low"   # SCHD-style dividend defensive
    assert f(0.75, 1.0) == "low"                       # modest beta + low realized vol
    assert f(0.83, None) == "medium"                   # JEPQ-style covered-call growth
    assert f(0.75, 2.2, div_yield_pct=0.76) == "medium"  # V-style low-beta mega-cap
    assert f(1.2, None) == "high"                      # beta > 1
    assert f(0.9, 5.0) == "high"                       # high realized volatility
    assert f(0.95, None, sector="Technology") == "high"  # high-vol sector escalation
    assert f(0.7, None, sector="Utilities") == "low"   # defensive sector at modest beta
    assert f(1.1, None, sector="Utilities") == "high"  # ...but real beta still wins
    assert f(None, None) is None                       # no data -> falls through


def test_no_hardcoded_symbol_pins():
    """2026-07-14.2 requirement: classification is dynamic — no ETFs pinned."""
    assert not (hf._policy().get("symbol_tier_overrides") or {}), \
        "symbol_tier_overrides must stay empty; add symbols only as operator decisions"


def test_vol_tier_resolution_uses_state_or_cache():
    """A held symbol with beta data resolves via the vol_tier step (bucket still wins)."""
    fam, src = hf.classify_family("ANET")
    assert fam == "vol_high" and src.startswith("vol_tier:high"), (fam, src)
    fam, src = hf.classify_family("SCHD")   # bucket dividend_income beats vol tier
    assert fam == "income_defensive" and "bucket" in src


def test_regime_adjustments():
    """risk_on widens ONLY vol_high trail cap; risk_off tightens all caps;
    neutral/None changes nothing; floors always hold."""
    base = hf.protection_bounds("vol_high")
    on = hf.protection_bounds("vol_high", regime="risk_on")
    assert on["trail_max_pct"] == base["trail_max_pct"] + 1.0
    assert on["regime_adjustment_pct"] == 1.0 and on["regime"] == "risk_on"
    med_on = hf.protection_bounds("vol_medium", regime="risk_on")
    assert med_on["trail_max_pct"] == hf.protection_bounds("vol_medium")["trail_max_pct"], \
        "risk_on must not widen non-high tiers"
    off = hf.protection_bounds("vol_medium", regime="risk_off")
    b = hf.protection_bounds("vol_medium")
    assert off["stop_max_pct"] == b["stop_max_pct"] - 1.0
    assert off["trail_max_pct"] == b["trail_max_pct"] - 1.0
    assert off["stop_max_pct"] >= off["stop_min_pct"] + 0.5
    neutral = hf.protection_bounds("vol_high", regime="neutral")
    assert neutral["trail_max_pct"] == base["trail_max_pct"]
    none_r = hf.protection_bounds("vol_high", regime=None)
    assert "regime" not in none_r


def test_current_regime_fail_soft_and_posture_map():
    r = hf.current_regime()
    assert r["posture"] in ("risk_on", "risk_off", "neutral")
    lm = (hf._policy().get("regime_adjustments") or {}).get("label_map") or {}
    assert "risk_on_trend" in (lm.get("risk_on") or [])
    assert "risk_off" in (lm.get("risk_off") or [])
    assert "high_volatility" in (lm.get("risk_off") or [])


def test_conviction_modifier_small_stock_tightens():
    full = hf.protection_bounds("vol_medium", position_value_usd=50_000, is_stock=True)
    small = hf.protection_bounds("vol_medium", position_value_usd=5_000, is_stock=True)
    assert small["stop_max_pct"] == full["stop_max_pct"] - 1.0
    assert small.get("conviction_tightened_pct") == 1.0
    etf = hf.protection_bounds("vol_medium", position_value_usd=5_000, is_stock=False)
    assert etf["stop_max_pct"] == full["stop_max_pct"], "conviction applies to stocks only"


def test_refresh_script_is_advisory_only():
    src = (ROOT / "scripts" / "volatility_tier_refresh.py").read_text()
    for bad in ("schwab_transport", "place_order", "submit_order", "alpaca_stop_manager"):
        assert bad not in src


def test_migration_state_file_and_endpoint_source():
    """The Policy panel's endpoint serves the report state file (disk read, never
    computed inline) and the report stays advisory with no bulk-apply concept."""
    import json
    p = ROOT / "data" / "state" / "stop_policy_migration_latest.json"
    assert p.exists(), "run scripts/stop_policy_migration_report.py first"
    rep = json.loads(p.read_text())
    for k in ("generated_at", "policy_version", "regime", "diverged", "divergences", "rows", "note"):
        assert k in rep, f"missing {k}"
    assert "advisory only" in rep["note"] and "no bulk apply" in rep["note"]
    api = (ROOT / "scripts" / "api_v2.py").read_text()
    assert "/api/v2/portfolio/stop-policy-migration" in api
    fn = api.split("def _portfolio_stop_policy_migration")[1].split("\ndef ")[0]
    assert "stop_policy_migration_latest.json" in fn
    assert "classify_family" not in fn, "endpoint must be a disk read, not inline compute"


def test_rotation_engine_surfaces_tier_without_scoring():
    """Rotation evidence carries stop_tier/volatility_tier but the tier never
    changes trim/add scores (advisory surfacing only)."""
    src = (ROOT / "scripts" / "rotation_intelligence_engine.py").read_text()
    block = src.split('evidence["stop_tier"]')[1].split("except Exception")[0]
    assert "trim" not in block and "add" not in block, \
        "tier surfacing must not touch scoring"
    assert 'evidence["volatility_tier"]' in src


def test_no_bulk_apply_in_ui():
    """CC v3 must not grow a bulk widen/apply-all control (per-order 2FA rule)."""
    for rel in ("apps/command-center-v3/src/components/StopManagement.tsx",
                "apps/command-center-v3/src/components/HoldingProtectionActions.tsx"):
        src = (ROOT / rel).read_text().lower()
        for bad in ("widen all", "apply all", "bulk apply", "apply-recommended-all"):
            assert bad not in src, f"'{bad}' found in {rel}"


def test_lifecycle_yaml_still_parses_with_linkage_note():
    import yaml
    d = yaml.safe_load((ROOT / "config" / "hermes_holdings_lifecycle.yaml").read_text())
    assert "panel_limit" in d
    assert "stop_rules" not in d, "stop rules must live only in stop_policy.yaml"


if __name__ == "__main__":
    for k, v in sorted(globals().items()):
        if k.startswith("test_"):
            v(); print("OK", k)
    print("ALL PASSED")
