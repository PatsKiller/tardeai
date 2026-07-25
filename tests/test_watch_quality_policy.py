from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import watch_quality_policy as quality


def quality_facts(**overrides):
    facts = {
        "symbol": "QUALITY",
        "live_price": 100.0,
        "atr": 3.0,
        "rvol": 1.1,
        "float_m": 500.0,
        "rsi": 55.0,
        "sma50": 92.0,
        "bars_used": 90,
        "instrument_type": "STOCK",
        "quote_type": "EQUITY",
        "fundamentals": {
            "market_cap_usd_millions": 20_000.0,
            "pe": 20.0,
            "ps": 5.0,
            "eps_past_5y": 15.0,
            "sales_past_5y": 10.0,
            "profit_margin_pct": 20.0,
            "roic_pct": 16.0,
            "total_debt_equity": 0.3,
            "current_ratio": 2.0,
            "short_float_pct": 3.0,
            "shares_outstanding_m": 600.0,
        },
    }
    for key, value in overrides.items():
        if key == "fundamentals":
            facts["fundamentals"] = value
        else:
            facts[key] = value
    return facts


def current_technicals():
    return {"overall_freshness": "CURRENT"}


def test_quality_operating_company_is_admitted():
    result = quality.evaluate_admission(
        quality_facts(),
        technical_snapshot=current_technicals(),
        ticket={"structure": "PULLBACK_SWING"},
        family="SWING",
    )

    assert result["state"] == quality.ADMITTED
    assert result["new_entry_allowed"] is True
    assert result["hard_failures"] == []


def test_low_price_low_float_extreme_volatility_is_quarantined():
    facts = quality_facts(
        live_price=4.50,
        atr=0.70,
        float_m=8.0,
        fundamentals={
            **quality_facts()["fundamentals"],
            "market_cap_usd_millions": 180.0,
        },
    )
    result = quality.evaluate_admission(
        facts,
        technical_snapshot=current_technicals(),
        ticket={"structure": "PULLBACK_SWING"},
        family="SWING",
    )

    assert result["state"] == quality.QUARANTINED
    assert result["new_entry_allowed"] is False
    joined = " | ".join(result["hard_failures"])
    assert "quality floor" in joined
    assert "low-float exclusion" in joined
    assert "extreme-volatility ceiling" in joined


def test_fundamentally_unattractive_rich_preprofit_name_is_quarantined():
    fundamentals = {
        "market_cap_usd_millions": 2_000.0,
        "ps": 80.0,
        "eps_past_5y": -35.0,
        "sales_past_5y": -10.0,
        "profit_margin_pct": -80.0,
        "roic_pct": -30.0,
        "total_debt_equity": 3.5,
        "current_ratio": 0.6,
        "short_float_pct": 22.0,
        "shares_outstanding_m": 100.0,
    }
    result = quality.evaluate_admission(
        quality_facts(fundamentals=fundamentals),
        technical_snapshot=current_technicals(),
        ticket={"structure": "PULLBACK_SWING"},
        family="SWING",
    )

    assert result["state"] == quality.QUARANTINED
    assert result["thesis_state"] == "FUNDAMENTALLY_UNATTRACTIVE"
    assert any("P/S" in reason for reason in result["hard_failures"])


def test_missing_quality_evidence_is_research_only_not_fabricated():
    result = quality.evaluate_admission(
        {
            "symbol": "UNKNOWN",
            "live_price": 30.0,
            "atr": 1.5,
            "rsi": 50.0,
            "instrument_type": "STOCK",
            "fundamentals": {},
        },
        technical_snapshot=current_technicals(),
        ticket={"structure": "PULLBACK_SWING"},
        family="SWING",
    )

    assert result["state"] == quality.RESEARCH_ONLY
    assert result["new_entry_allowed"] is False
    assert any("unavailable" in warning or "insufficient" in warning
               for warning in result["warnings"])


def test_held_name_with_quality_gaps_is_management_only():
    result = quality.evaluate_admission(
        {
            "symbol": "HELD",
            "live_price": 30.0,
            "atr": 1.5,
            "rsi": 50.0,
            "instrument_type": "STOCK",
            "fundamentals": {},
        },
        technical_snapshot=current_technicals(),
        ticket={"structure": "PULLBACK_SWING"},
        family="SWING",
        ownership={"held": True},
    )

    assert result["management_only"] is True
    assert result["new_entry_allowed"] is False
    assert any("management only" in reason for reason in result["reasons"])


def test_scalp_family_is_outside_watch_mandate():
    result = quality.evaluate_admission(
        quality_facts(),
        technical_snapshot=current_technicals(),
        ticket={"structure": "MOMENTUM_SCALP"},
        family="SWING",
    )

    assert result["state"] == quality.QUARANTINED
    assert any("non-scalping Watch mandate" in reason
               for reason in result["hard_failures"])
