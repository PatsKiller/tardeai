"""Operator decision 2026-09-15: small caps are in scope and labeled as small caps, not quarantined."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import watch_quality_policy as quality  # noqa: E402
from lib.market_cap_label import cap_label, cap_label_from_usd, pill  # noqa: E402

BASE = {
    "symbol": "SMALL", "live_price": 24.0, "atr": 0.9, "rvol": 1.2, "float_m": 60.0,
    "instrument_type": "STOCK", "quote_type": "EQUITY",
    "fundamentals": {"market_cap_usd_millions": 20_000.0, "pe": 18.0, "ps": 2.0, "eps_past_5y": 12.0,
                     "sales_past_5y": 9.0, "profit_margin_pct": 11.0, "roic_pct": 13.0,
                     "total_debt_equity": 0.4, "current_ratio": 1.8, "short_float_pct": 4.0,
                     "shares_outstanding_m": 70.0},
}


def facts(cap_m):
    f = copy.deepcopy(BASE)
    f["fundamentals"]["market_cap_usd_millions"] = cap_m
    return f


def test_bands():
    assert cap_label(20)["code"] == "NANO_CAP"
    assert cap_label(180)["code"] == "MICRO_CAP"
    assert cap_label(1_400)["code"] == "SMALL_CAP" and cap_label(1_400)["is_small"] is True
    assert cap_label(5_000)["code"] == "MID_CAP" and cap_label(5_000)["is_small"] is False
    assert cap_label(50_000)["code"] == "LARGE_CAP"
    assert cap_label(3_000_000)["code"] == "MEGA_CAP"
    assert cap_label(None)["code"] == "UNKNOWN" and cap_label("x")["is_small"] is None
    assert cap_label_from_usd(1.4e9)["code"] == "SMALL_CAP"
    assert pill(cap_label(1_400)) == "Small cap · $1.4B" and pill(cap_label(180)) == "Micro cap · $180M"
    assert pill(cap_label(None)) == ""


def test_policy_file_admits_small_caps_with_label():
    assert quality.SMALL_CAPS_ADMITTED_WITH_LABEL is True


def test_small_cap_is_not_quarantined_and_carries_label():
    r = quality.evaluate_admission(facts(1_400), technical_snapshot={"overall_freshness": "CURRENT"})
    assert not any("market cap" in h for h in r["hard_failures"])
    assert not any("market cap" in w for w in r["warnings"])
    assert r["market_cap_label"] == "SMALL_CAP" and "Small cap ($1400M)" in r["labels"]


def test_micro_cap_below_old_floor_is_labeled_not_hard_failed():
    r = quality.evaluate_admission(facts(180), technical_snapshot={"overall_freshness": "CURRENT"})
    assert not any("quality floor" in h and "market cap" in h for h in r["hard_failures"])
    assert r["market_cap_label"] == "MICRO_CAP"


def test_large_cap_has_label_but_no_small_cap_text():
    r = quality.evaluate_admission(facts(50_000), technical_snapshot={"overall_freshness": "CURRENT"})
    assert r["market_cap_label"] == "LARGE_CAP" and r["labels"] == []


def test_missing_cap_is_still_a_data_gap():
    r = quality.evaluate_admission(facts(None), technical_snapshot={"overall_freshness": "CURRENT"})
    assert "market capitalization unavailable" in r["warnings"] and r["market_cap_label"] == "UNKNOWN"


def test_flag_off_restores_the_floor(monkeypatch):
    monkeypatch.setattr(quality, "SMALL_CAPS_ADMITTED_WITH_LABEL", False)
    r = quality.evaluate_admission(facts(180), technical_snapshot={"overall_freshness": "CURRENT"})
    assert any("below the $500M quality floor" in h for h in r["hard_failures"])


def test_price_and_float_gates_unchanged():
    f = facts(180); f["live_price"] = 3.0; f["float_m"] = 5.0
    r = quality.evaluate_admission(f, technical_snapshot={"overall_freshness": "CURRENT"})
    assert any("quality floor" in h and "price" in h for h in r["hard_failures"])
    assert any("low-float" in h for h in r["hard_failures"])
