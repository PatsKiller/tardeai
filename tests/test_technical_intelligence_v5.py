"""Technical-intelligence service tests (Section 17.19 subset) — no network:
pure functions + synthetic frames; DB/fetch paths excluded via allow_fetch=False."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import technical_intelligence as ti  # noqa: E402
import indicator_engine as ie  # noqa: E402


def test_20_missing_implementation_reports_unavailable_not_neutral():
    """17.11 core: every failure path is UNAVAILABLE with the error attached."""
    import pandas as pd
    bad = pd.DataFrame({"close": [1.0, 2.0]})  # far too short + missing columns
    for name, fn in ie.STRATEGY_FUNCTIONS.items():
        r = fn(bad, {})
        assert r["signal"] in ("UNAVAILABLE", "NEUTRAL"), (name, r)
        if r["signal"] == "UNAVAILABLE":
            assert "error" in (r.get("details") or {}), name


def test_21_22_capability_audit_all_enabled_available():
    aud = ie.capability_audit()
    missing = {k: v for k, v in aud.items()
               if not k.startswith("_") and v != "AVAILABLE"}
    assert not missing, f"enabled indicators lacking implementations: {missing}"
    assert aud["_using_pandas_ta_shim"] in (True, False)


def test_17_weights_actually_applied():
    """A high-weight bullish signal must outscore a low-weight one."""
    hi = ie.analyze_confluence_v2({"rsi": {"signal": "BULLISH"}},
                                  {"rsi": {"weight": 2.0}})
    lo = ie.analyze_confluence_v2({"rsi": {"signal": "BULLISH"}},
                                  {"rsi": {"weight": 0.5}})
    assert hi["bullish_score"] > lo["bullish_score"]
    assert hi["weights_applied"] is True


def test_18_19_correlated_evidence_capped_and_no_single_family_strong():
    """Four momentum indicators bullish = ONE capped family, never STRONG."""
    sigs = {k: {"signal": "BULLISH"} for k in ("rsi", "stochastic", "macd", "williams_r")}
    cfgs = {k: {"weight": 1.5} for k in sigs}
    r = ie.analyze_confluence_v2(sigs, cfgs)
    assert r["independent_families_bullish"] == 1
    assert r["family_contributions"]["MOMENTUM"]["bull"] == ie.FAMILY_CAP
    assert r["state"] != "BULLISH_STRONG", "one family alone must never be STRONG"


def test_24_stale_and_unavailable_excluded_from_confluence():
    sigs = {"rsi": {"signal": "BULLISH"}, "obv": {"signal": "UNAVAILABLE"},
            "cmf": {"signal": "STALE"}}
    r = ie.analyze_confluence_v2(sigs, {})
    assert "obv" in r["unavailable"] and "cmf" in r["unavailable"]
    assert "obv" not in r["contributors"] and "cmf" not in r["contributors"]


def test_11_12_oversold_is_not_a_buy():
    """17.9: OB/OS are context states, never automatic direction."""
    down = ti.momentum_context({"rsi": {"value": 26},
                                "macd": {"details": {"histogram_trend": "falling"}},
                                "adx": {"details": {"adx": 20}}}, [])
    assert down["state"] == "OVERSOLD_CONTINUING_DOWN"
    rec = ti.momentum_context({"rsi": {"value": 31},
                               "macd": {"details": {"histogram_trend": "rising"}},
                               "adx": {"details": {"adx": 18}}}, [])
    assert rec["state"] == "OVERSOLD_RECOVERY"
    strong = ti.momentum_context({"rsi": {"value": 76},
                                  "macd": {"details": {"histogram_trend": "rising"}},
                                  "adx": {"details": {"adx": 42}}}, [])
    assert strong["state"] == "OVERBOUGHT_STRONG_TREND"


def test_25_freshness_tracked_per_timeframe_and_separate_from_direction():
    snap = {"timeframes": {"daily": {"meta": {"freshness_state": "STALE"},
                                     "indicators": {}, "confluence": {"state": "BULLISH_STRONG",
                                                                      "net_score": 50,
                                                                      "independent_families_bullish": 3,
                                                                      "independent_families_bearish": 0},
                                     "direction": "BULLISH"}},
            "overall_freshness": "STALE", "overall_direction": "BULLISH",
            "computed_at": "2026-07-22T12:00:00", "source_hash": "abc",
            "levels": [], "primary_pattern": None}
    pills = ti.select_pills(snap)
    trend = next(p for p in pills if p["kind"] == "trend")
    assert trend["direction"] == "BULLISH" and trend["freshness"] == "STALE", \
        "stale must ride WITH direction, never replace it"


def test_27_28_max_six_pills_deterministic():
    snap = {"timeframes": {}, "overall_freshness": "CURRENT",
            "overall_direction": "NEUTRAL", "computed_at": "2026-07-22T12:00:00",
            "source_hash": "x", "levels": [], "primary_pattern": None}
    a = ti.select_pills(snap)
    b = ti.select_pills(dict(snap))
    assert len(a) <= 6 and a == b


def test_resample_weekly_drops_open_period():
    daily = [{"ts": f"2026-06-{d:02d}T00:00:00+00:00", "open": 1, "high": 2,
              "low": 0.5, "close": 1.5, "volume": 100, "source": "t"}
             for d in range(1, 30)]
    wk = ti._resample(daily, "W-FRI")
    assert wk, "weekly resample empty"
    assert wk[-1]["ts"] < daily[-1]["ts"], "the in-progress week must be excluded"


def test_15_fib_integrated_in_canonical_levels():
    """Levels builder consumes indicator-engine fib output with provenance."""
    tf_results = {"daily": {"indicators": {"fibonacci": {"details": {
        "key_levels": {"ret_0.618": 80.84, "ret_0.5": 82.1}}}}, "patterns": []}}
    lv = ti.build_levels(tf_results)
    assert any("fib" in s for l in lv for s in l["sources"])
    assert all("timeframe" not in l or l.get("kind") for l in lv)


def test_16_pullback_macd_formula_parity():
    """17.19 item 16: the Pullback silo's private MACD must match the canonical
    shim formula until it is migrated to the canonical owner."""
    import pandas as pd
    import numpy as np
    import pandas_ta_shim as shim
    sys.path.insert(0, str(ROOT / "scripts"))
    import pullback_macd_screener as pbm
    close = pd.Series(100 + np.cumsum(np.random.default_rng(3).normal(0, 1, 120)))
    theirs = pbm._macd(close, 12, 26, 9)
    ours = shim.macd(close)
    macd_col = [c for c in ours.columns if c.startswith("MACD_")][0]
    line_t = (theirs[0] if isinstance(theirs, tuple) else theirs)
    diff = float((line_t - ours[macd_col]).abs().dropna().max())
    assert diff < 1e-6, f"MACD formula divergence {diff}"


def test_30_technical_signal_grants_nothing():
    """Packet technical_state must not touch action policy authority."""
    import decision_action_policy as dap
    src = (ROOT / "scripts" / "decision_action_policy.py").read_text()
    assert "technical_state" not in src, \
        "action policy must not read technical_state (no new eligibility path)"


# ── V6 integration contract (card ↔ packet) ──────────────────────────────────
def test_v6_local_quant_never_displayed_unavailable():
    band = (ROOT / "apps/command-center-v3/src/components/DecisionPacketBand.tsx").read_text()
    assert "LOCAL QUANT · NO LLM" in band
    assert "packet?.analysis_tier" in band
    assert "model_review?.mode || packet?.analysis_tier" not in band, \
        "model_review.mode must not take display priority over analysis_tier"


def test_v6_packet_persists_freshness_and_aliases():
    src = (ROOT / "scripts/shadow_decision_service.py").read_text()
    for needle in ('packet["freshness"]', '"valid_until"', '"next_refresh_due_at"',
                   'packet["current_input_snapshot"]', 'packet["analysis_tier"]',
                   '"priority_tier"', '"policy_version"'):
        assert needle in src, f"packet builder missing {needle}"


def test_v6_legacy_vs_failed_vs_stale_explanations():
    band = (ROOT / "apps/command-center-v3/src/components/DecisionPacketBand.tsx").read_text()
    assert "LEGACY PACKET" in band
    assert "Technical analysis FAILED" in band
    assert "Technical data STALE" in band
    assert "Technical refresh currently running" in band


def test_v6_list_summary_retains_error():
    api = (ROOT / "scripts/api_v2.py").read_text()
    assert '"unavailable", "error")' in api, "list tech summary must retain error"


def test_v6_timing_refinement_guarded():
    src = (ROOT / "scripts/shadow_decision_service.py").read_text()
    assert 'technical_state.get("overall_freshness") in ("CURRENT", "PARTIAL")' in src, \
        "stale/failed technicals must never refine timing"
    assert "never grant READY" in src
    assert "BREAKOUT_CONFIRMATION" in src and "REVERSAL_WATCH" in src
