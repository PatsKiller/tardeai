#!/usr/bin/env python3
"""EARNINGS-SPREADS Stage 1 — registry additions + earnings event model tests.

Covers (operator spec Parts A + B): registry loads with the earnings vertical
pair (debit TESTING_PAPER / credit BLOCKED_INITIAL), BLOCKED_INITIAL is
valid-but-unscannable (paper_enabled=true under it fails closed), live locks
still fire, matcher-compat (Stage 2: the debit lane's matcher reports honest
not_applicable outside the event window); event-window math, implied
move from a synthetic straddle (+ strangle fallback + honest quote degrade),
historical-move honesty (single stored past date, never fabricated), thesis
mapping, confidence formula bounds, crush-estimate honesty, and a
forbidden-imports AST sweep on the new module.

    .venv/bin/python -m pytest tests/test_options_earnings_event_model.py -q
"""
from __future__ import annotations

import ast
import copy
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib.options_pipeline import earnings_event_model as eem  # noqa: E402
from lib.options_pipeline import strategy_matcher as sm       # noqa: E402
from lib.options_pipeline import universe as uni              # noqa: E402

TODAY = date(2026, 7, 6)
EARN = "2026-07-15"          # 9 days out — inside the 10/2 window
IV_SERIES_25 = [30.0 + i * 0.5 for i in range(25)]   # 25 stored days, 30→42


def _write(tmp_path, doc, name="r.yaml"):
    p = tmp_path / name
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


# ── synthetic chain snapshot fixtures ────────────────────────────────────────

def _leg(side, strike, bid, ask, *, iv=40.0, dte=11, spread_pct=None):
    mid = round((bid + ask) / 2.0, 4) if bid and ask else None
    if spread_pct is None and mid:
        spread_pct = round((ask - bid) / mid * 100.0, 2)
    return {"side": side, "strike": float(strike), "bid": bid, "ask": ask,
            "mid": mid, "spread_pct": spread_pct, "volume": 60, "oi": 600,
            "delta": None, "iv": iv, "dte": dte, "liquidity_score": 60}


def _snapshot(contracts=None, *, spot=100.0, exp="2026-07-17", dte=11,
              extra_exps=()):
    if contracts is None:
        contracts = [_leg("call", 100, 2.4, 2.6), _leg("put", 100, 2.4, 2.6)]
    exps = [{"exp": "2026-07-10", "dte": 4,
             "contracts": [_leg("call", 100, 1.0, 1.2, dte=4),
                           _leg("put", 100, 1.0, 1.2, dte=4)],
             "liquidity_score": 60},
            {"exp": exp, "dte": dte, "contracts": contracts,
             "liquidity_score": 60}] + list(extra_exps)
    return {"available": True, "symbol": "TST", "underlying_price": spot,
            "expirations": exps, "liquidity_score": 60}


NO_CHAIN = {"available": False, "reason": "weekend — no chain (test fixture)"}


def _build(**kw):
    kw.setdefault("chain_snapshot", _snapshot())
    kw.setdefault("earnings_date", EARN)
    kw.setdefault("today", TODAY)
    kw.setdefault("context", {"verdict": "sell", "held_shares": None})
    kw.setdefault("past_earnings_dates", [])         # honest: no history source
    kw.setdefault("iv_history_series", IV_SERIES_25)
    return eem.build_event_json("TST", **kw)


# ── (1) event window math ────────────────────────────────────────────────────

def test_days_to_earnings_and_window():
    ev = _build()
    assert ev["days_to_earnings"] == 9
    assert ev["earnings_date"] == {"date": EARN, "source": "caller_supplied"}
    assert ev["event_window"] == {"days_before": 10, "days_after": 2,
                                  "in_window": True}
    assert "event_far" not in ev["risk_flags"]
    assert "event_stale" not in ev["risk_flags"]
    assert ev["event_confidence_detail"]["components"]["event_proximity"] == 1.0


def test_event_far_and_stale_flags():
    far = _build(earnings_date="2026-07-30")          # 24 days out
    assert far["days_to_earnings"] == 24
    assert far["event_window"]["in_window"] is False
    assert "event_far" in far["risk_flags"]
    assert far["event_confidence_detail"]["components"]["event_proximity"] == 0.25
    near_far = _build(earnings_date="2026-07-20")     # 14 days: 10 < 14 <= 20
    assert near_far["event_confidence_detail"]["components"]["event_proximity"] == 0.6
    stale = _build(earnings_date="2026-07-01")        # 5 days past (> after=2)
    assert stale["days_to_earnings"] == -5
    assert "event_stale" in stale["risk_flags"]
    assert stale["event_confidence_detail"]["components"]["event_proximity"] == 0.0
    post = _build(earnings_date="2026-07-05")         # 1 day past — post-event lane
    assert post["event_window"]["in_window"] is True


def test_no_earnings_date_degrades_honestly():
    ev = _build(earnings_date=None, past_earnings_dates=[])
    # caller passed None → live lookup runs; with no DB row/json entry for TST
    # the date degrades honestly (never guessed)
    if ev["earnings_date"]["date"] is None:            # normal CI path
        assert ev["days_to_earnings"] is None
        assert "no_earnings_date" in ev["risk_flags"]
        assert ev["earnings_date"]["reason"]
        assert ev["nearest_expiration_after_earnings"]["available"] is False


def test_window_days_come_from_config():
    ev = _build(earnings_date="2026-07-30",
                config={"earnings_window_days_before": 30,
                        "earnings_window_days_after": 2})
    assert ev["event_window"]["in_window"] is True
    assert "event_far" not in ev["risk_flags"]


# ── (2) nearest expiration after the event ───────────────────────────────────

def test_event_expiration_selection():
    ev = _build()
    exp = ev["nearest_expiration_after_earnings"]
    assert exp == {"available": True, "exp": "2026-07-17", "dte": 11}


def test_no_expiration_after_event_degrades():
    ev = _build(earnings_date="2026-09-01")
    exp = ev["nearest_expiration_after_earnings"]
    assert exp["available"] is False and "no listed expiration" in exp["reason"]
    assert "no_expiration_after_earnings" in ev["risk_flags"]
    assert ev["implied_move_pct"]["available"] is False


# ── (3) implied move: straddle, strangle fallback, honest degrade ────────────

def test_implied_move_from_synthetic_straddle():
    ev = _build()   # call mid 2.5 + put mid 2.5 at strike 100, spot 100
    im = ev["implied_move_pct"]
    assert im["available"] is True
    assert im["method"] == "atm_straddle_mid"
    assert im["pct"] == 5.0
    assert im["strike"] == 100.0 and im["expiration"] == "2026-07-17"
    assert im["wide_quotes"] is False


def test_implied_move_strangle_fallback():
    contracts = [_leg("call", 100, 0, 0),            # ATM call quote dead
                 _leg("put", 100, 0, 0),             # ATM put quote dead
                 _leg("call", 105, 1.0, 1.2),        # usable OTM call (mid 1.1)
                 _leg("put", 95, 0.9, 1.1)]          # usable OTM put (mid 1.0)
    ev = _build(chain_snapshot=_snapshot(contracts))
    im = ev["implied_move_pct"]
    assert im["available"] is True
    assert im["method"] == "otm_strangle_fallback"
    assert im["pct"] == pytest.approx(2.1)           # (1.1 + 1.0) / 100
    assert {l["strike"] for l in im["legs"]} == {105.0, 95.0}


def test_implied_move_unusable_quotes_degrade():
    contracts = [_leg("call", 100, 0, 0), _leg("put", 100, 0, 0)]
    ev = _build(chain_snapshot=_snapshot(contracts))
    im = ev["implied_move_pct"]
    assert im["available"] is False and im["pct"] is None
    assert "no usable two-sided quotes" in im["reason"]
    assert "wide_quotes" in ev["risk_flags"]         # chain ok but move unusable


def test_implied_move_wide_quotes_flagged():
    contracts = [_leg("call", 100, 2.0, 3.0),        # 40% spread — wide
                 _leg("put", 100, 2.0, 3.0)]
    ev = _build(chain_snapshot=_snapshot(contracts))
    assert ev["implied_move_pct"]["available"] is True
    assert ev["implied_move_pct"]["wide_quotes"] is True
    assert "wide_quotes" in ev["risk_flags"]


def test_chain_unavailable_degrades_whole_chain_branch():
    ev = _build(chain_snapshot=NO_CHAIN)
    assert ev["nearest_expiration_after_earnings"]["available"] is False
    assert ev["implied_move_pct"]["available"] is False
    assert "weekend" in ev["implied_move_pct"]["reason"]
    assert "chain_unavailable" in ev["risk_flags"]
    # confidence completeness honestly drops (chain, implied move missing)
    assert ev["event_confidence_detail"]["components"]["data_completeness"] < 1.0


# ── (4) historical earnings moves — honesty first ────────────────────────────

BARS = [{"d": "2026-04-20", "close_price": 100.0},
        {"d": "2026-04-21", "close_price": 101.0},
        {"d": "2026-04-22", "close_price": 95.0},    # event date D
        {"d": "2026-04-23", "close_price": 94.0}]


def test_historical_move_from_daily_bars():
    out = eem.historical_earnings_moves(
        "TST", past_dates=["2026-04-22"], closes_fn=lambda s, d: BARS)
    assert out["available"] is True and out["samples"] == 1
    # into-event leg |95/101−1| = 5.94% beats out-of-event |94/95−1| = 1.05%
    assert out["avg_abs_move_pct"] == out["max_abs_move_pct"] == 5.94
    assert out["per_event"][0]["picked_leg"] == "close_to_close_into_event"
    assert "BMO/AMC" in out["per_event"][0]["method"]


def test_historical_no_dates_source_degrades():
    out = eem.historical_earnings_moves("TST", past_dates=[])
    assert out["available"] is False
    assert "no historical earnings dates source" in out["reason"]
    # a FUTURE date is not a past event — filtered, still an honest degrade
    out = eem.historical_earnings_moves("TST", past_dates=["2099-01-01"])
    assert out["available"] is False


def test_historical_missing_bars_degrades():
    out = eem.historical_earnings_moves(
        "TST", past_dates=["2026-04-22"], closes_fn=lambda s, d: [])
    assert out["available"] is False
    assert "no usable daily bars" in out["reason"]


def test_thin_history_flag_always_set_with_single_sample():
    ev = _build(past_earnings_dates=["2026-04-22"],
                closes_fn=lambda s, d: BARS)
    assert ev["historical_earnings_moves"]["available"] is True
    assert "thin_history" in ev["risk_flags"]        # samples 1 < 4 (structural)


# ── (5) thesis mapping ───────────────────────────────────────────────────────

@pytest.mark.parametrize("verdict,expected", [
    ("strong_buy", "bullish"), ("buy", "bullish"),
    ("sell", "bearish"), ("strong_sell", "bearish"), ("avoid", "bearish"),
    ("deteriorating", "bearish"), ("reduce", "bearish"),
    ("hold", "neutral"), (None, "unknown"),
])
def test_event_thesis_mapping(verdict, expected):
    ev = _build(context={"verdict": verdict, "held_shares": None})
    assert ev["event_thesis"] == expected
    if expected == "unknown":
        assert "thesis_unknown" in ev["risk_flags"]
        assert ev["event_thesis_source"] is None
    else:
        assert ev["event_thesis_source"]


def test_hedge_of_held_maps_bearish():
    ev = _build(context={"verdict": None, "held_shares": 100.0,
                         "hedge_of_held": True})
    assert ev["event_thesis"] == "bearish"
    assert ev["event_thesis_source"] == "hedge_of_held"


# ── (6) confidence formula — bounds + documented components ──────────────────

def test_confidence_full_house_is_one():
    ev = _build(context={"verdict": "strong_sell", "held_shares": None},
                past_earnings_dates=["2026-04-22"],
                closes_fn=lambda s, d: BARS)
    d = ev["event_confidence_detail"]
    assert d["components"] == {"thesis_strength": 1.0,
                               "data_completeness": 1.0,
                               "event_proximity": 1.0}
    assert ev["event_confidence"] == 1.0
    assert "clamp01" in d["formula"]


def test_confidence_bounds_over_grid():
    for verdict in ("strong_buy", "buy", "sell", "hold", None):
        for earn in (EARN, "2026-07-30", "2026-06-01", None):
            for snap in (_snapshot(), NO_CHAIN):
                ev = _build(context={"verdict": verdict, "held_shares": None},
                            earnings_date=earn, chain_snapshot=snap,
                            iv_history_series=[])
                assert 0.0 <= ev["event_confidence"] <= 1.0
                for v in ev["event_confidence_detail"]["components"].values():
                    assert 0.0 <= v <= 1.0


def test_confidence_ordering_thesis_strength():
    strong = _build(context={"verdict": "strong_sell", "held_shares": None})
    weak = _build(context={"verdict": "sell", "held_shares": None})
    unknown = _build(context={"verdict": None, "held_shares": None})
    assert strong["event_confidence"] > weak["event_confidence"] \
        > unknown["event_confidence"]


def test_confidence_weights_sum_to_one():
    ev = _build()
    assert sum(ev["event_confidence_detail"]["weights"].values()) == pytest.approx(1.0)


# ── (7) IV context + crush estimate honesty ──────────────────────────────────

def test_iv_rank_and_rich_flag():
    ev = _build()   # snapshot IV 40 vs series 30→42 → high rank
    ivc = ev["iv_context"]
    assert ivc["available"] is True and ivc["iv_rank"] > 70
    assert "iv_rich" in ev["risk_flags"]


def test_crush_estimate_labeled_and_computed():
    out = eem.crush_estimate(40.0, IV_SERIES_25)      # median 36.0
    assert out["available"] is True and out["is_estimate"] is True
    assert out["estimate_pct"] == 10.0                # (40−36)/40 × 100
    assert "ESTIMATE" in out["method"]


def test_crush_estimate_degrades_honestly():
    assert eem.crush_estimate(None, IV_SERIES_25)["available"] is False
    thin = eem.crush_estimate(40.0, [30.0] * 5)
    assert thin["available"] is False and "insufficient iv history" in thin["reason"]
    below = eem.crush_estimate(30.0, IV_SERIES_25)    # already below median
    assert below["available"] is True and below["estimate_pct"] == 0.0


def test_insufficient_iv_history_degrades_in_event_json():
    ev = _build(iv_history_series=[])
    assert ev["iv_context"]["available"] is False
    assert ev["post_earnings_iv_crush_estimate"]["available"] is False


# ── (8) registry: new strategies + BLOCKED_INITIAL + live locks ──────────────

@pytest.fixture()
def reg():
    return uni.load_strategy_registry()


def test_registry_has_earnings_vertical_pair(reg):
    s = reg["strategies"]
    assert "earnings_put_debit_spread" in s and "earnings_put_credit_spread" in s

    d = s["earnings_put_debit_spread"]
    assert d["family"] == "earnings_vertical_debit"
    assert d["direction"] == "bearish"
    assert d["status"] == "TESTING_PAPER"    # spec 'research_paper' → loader enum
    assert d["paper_enabled"] is True and d["alpaca_paper_enabled"] is False
    assert len(d["legs"]) == 2
    sel = d["selection"]
    assert sel["dte_buckets"] == [7, 14, 21, 30, 45]
    assert sel["earnings_window_days_before"] == 10
    assert sel["earnings_window_days_after"] == 2
    assert sel["min_event_confidence"] == 0.65
    assert sel["required_thesis"] == "bearish_or_hedge"
    assert sel["max_spread_package_slippage_pct"] == 8
    assert sel["min_open_interest_each_leg"] == 250
    assert sel["min_volume_each_leg"] == 10
    assert sel["max_debit_pct_of_underlying"] == 6
    assert sel["max_loss_usd_paper"] == 1000

    c = s["earnings_put_credit_spread"]
    assert c["family"] == "earnings_vertical_credit"
    assert c["direction"] == "bullish_or_neutral"
    assert c["status"] == "BLOCKED_INITIAL"
    assert c["paper_enabled"] is False and c["alpaca_paper_enabled"] is False
    assert c["selection"]["min_credit_pct_of_width"] == 20
    assert c["selection"]["assignment_risk_required"] is True
    assert c["selection"]["min_event_confidence"] == 0.65

    for sid in ("earnings_put_debit_spread", "earnings_put_credit_spread"):
        row = s[sid]
        assert row["live_enabled"] is False
        assert row["live_exception_allowed"] is False
        assert row["live_exception_requires_2fa"] is True
        assert row["required_permission_level"] == "operator"
        assert row["liquidity_gates"] == {"max_spread_pct": 8.0, "min_oi": 250,
                                          "min_volume": 10}
        assert row["max_contracts_paper"] == 1


def test_blocked_initial_is_valid_but_unscannable(tmp_path, reg):
    # as-shipped: loads fine
    assert reg["strategies"]["earnings_put_credit_spread"]["status"] == "BLOCKED_INITIAL"
    # flipping paper_enabled WITHOUT changing the status fails closed
    doc = copy.deepcopy(reg)
    doc["strategies"]["earnings_put_credit_spread"]["paper_enabled"] = True
    with pytest.raises(uni.RegistryConfigError, match="BLOCKED_INITIAL"):
        uni.load_strategy_registry(_write(tmp_path, doc))
    doc = copy.deepcopy(reg)
    doc["strategies"]["earnings_put_credit_spread"]["alpaca_paper_enabled"] = True
    with pytest.raises(uni.RegistryConfigError):
        uni.load_strategy_registry(_write(tmp_path, doc, "b.yaml"))
    # the explicit unlock path: change the status too → loads
    doc = copy.deepcopy(reg)
    doc["strategies"]["earnings_put_credit_spread"]["status"] = "TESTING_PAPER"
    doc["strategies"]["earnings_put_credit_spread"]["paper_enabled"] = True
    out = uni.load_strategy_registry(_write(tmp_path, doc, "c.yaml"))
    assert out["strategies"]["earnings_put_credit_spread"]["paper_enabled"] is True


def test_live_locks_still_fire_on_new_rows(tmp_path, reg):
    for sid in ("earnings_put_debit_spread", "earnings_put_credit_spread"):
        for field in ("live_enabled", "live_exception_allowed"):
            doc = copy.deepcopy(reg)
            doc["strategies"][sid][field] = True
            with pytest.raises(uni.LivePolicyViolation):
                uni.load_strategy_registry(
                    _write(tmp_path, doc, f"{sid}_{field}.yaml"), env={})


def test_unknown_status_still_fails_closed(tmp_path, reg):
    doc = copy.deepcopy(reg)
    doc["strategies"]["earnings_put_debit_spread"]["status"] = "research_paper"
    with pytest.raises(uni.RegistryConfigError, match="unknown status"):
        uni.load_strategy_registry(_write(tmp_path, doc))


# ── (9) matcher compat (updated for EARNINGS-SPREADS Stage 2: the debit lane
# now HAS a matcher — an out-of-window event stays honest not_applicable; the
# blocked credit lane is unchanged) ──────────────────────────────────────────

def test_matcher_reports_new_strategies_not_applicable(reg):
    res = sm.run_matchers(
        "NVDA", {"verdict": "sell", "held_shares": None},
        ["earnings_put_debit_spread", "earnings_put_credit_spread"],
        registry=reg,
        snapshot={"available": False, "reason": "not fetched (test)"},
        earnings_date="2099-01-01")   # deterministic: far outside the window
    r = res["strategy_results"]
    # debit lane (Stage 2 matcher): event far outside the window → not_applicable
    assert r["earnings_put_debit_spread"]["status"] == "not_applicable"
    assert "no earnings in window" in r["earnings_put_debit_spread"]["reason"]
    # credit lane: blocked initially → surfaced via paper_enabled false + status
    assert r["earnings_put_credit_spread"]["status"] == "not_applicable"
    assert "paper_enabled false" in r["earnings_put_credit_spread"]["reason"]
    assert "BLOCKED_INITIAL" in r["earnings_put_credit_spread"]["reason"]


# ── (10) forbidden imports — event model stays broker-free ───────────────────

FORBIDDEN_MODULES = {
    "options_order_pilot", "options_pilot_arm", "brokers", "approval_service",
    "schwab_transport", "schwab_pilot_orders", "alpaca_trade_api", "alpaca",
    "trade_executor", "order_executor", "telegram_2fa", "two_factor",
    "options_execution_policy",
}


def test_event_model_has_no_forbidden_imports():
    tree = ast.parse((ROOT / "scripts" / "lib" / "options_pipeline" /
                      "earnings_event_model.py").read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.update({a.name, a.name.split(".")[0]})
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.update({node.module, node.module.split(".")[0]})
    assert not mods & FORBIDDEN_MODULES
