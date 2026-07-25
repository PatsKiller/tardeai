from pathlib import Path
import sys


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import strategy_ticket_validator as validator


def quality_facts():
    return {
        "symbol": "QUALITY",
        "live_price": 100.0,
        "enriched_price": 100.0,
        "atr": 3.0,
        "rvol": 1.0,
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


def valid_ticket(price=100.0):
    return {
        "structure": "PULLBACK_SWING",
        "entry_mode": "PULLBACK",
        "entry_state": "READY_PULLBACK",
        "entry_zone": [price - 1.0, price + 1.0],
        "limit_price": price,
        "stop_price": price - 5.0,
        "targets": [price + 10.0],
        "risk_reward": 2.0,
        "trigger": "hold the entry zone",
        "invalidation": f"close below {price - 5.0}",
        "mechanics_current": True,
    }


def test_clean_quality_and_arithmetic_pass_together():
    result = validator.validate_ticket(
        "QUALITY",
        "SWING",
        valid_ticket(),
        quality_facts(),
        technical_snapshot={"overall_freshness": "CURRENT"},
        ownership={"held": False},
    )

    assert result["state"] == "PASS"
    assert result["quality_admission"]["state"] == "ADMITTED"
    assert result["recomputed"]["risk_reward"] == 2.0


def test_valid_arithmetic_cannot_rescue_low_quality_instrument():
    facts = quality_facts()
    facts.update(live_price=4.50, enriched_price=4.50, atr=0.70, float_m=8.0)
    facts["fundamentals"] = {
        **facts["fundamentals"],
        "market_cap_usd_millions": 180.0,
    }
    ticket = valid_ticket(4.50)
    ticket.update(
        entry_zone=[4.40, 4.60],
        stop_price=4.00,
        targets=[5.50],
        risk_reward=2.0,
        invalidation="close below 4.00",
    )

    result = validator.validate_ticket(
        "LOWQ",
        "SWING",
        ticket,
        facts,
        technical_snapshot={"overall_freshness": "CURRENT"},
        ownership={"held": False},
    )

    assert result["recomputed"]["risk_reward"] is None  # admission fails before ticket arithmetic is promoted
    assert result["state"] == "FAIL"
    assert result["quality_admission"]["state"] == "QUARANTINED"
    assert any("quality admission" in reason for reason in result["hard_failures"])


def test_research_only_quality_strips_current_entry_even_when_numbers_are_valid():
    facts = {
        "symbol": "GAPS",
        "live_price": 30.0,
        "enriched_price": 30.0,
        "atr": 1.5,
        "rsi": 50.0,
        "instrument_type": "STOCK",
        "fundamentals": {},
    }
    ticket = valid_ticket(30.0)
    ticket.update(
        entry_zone=[29.5, 30.5],
        stop_price=28.0,
        targets=[34.0],
        risk_reward=2.0,
        invalidation="close below 28.00",
    )

    result = validator.validate_ticket(
        "GAPS",
        "SWING",
        ticket,
        facts,
        technical_snapshot={"overall_freshness": "CURRENT"},
        ownership={"held": False},
    )

    assert result["state"] == "FAIL"
    assert result["quality_admission"]["state"] == "RESEARCH_ONLY"
    assert any("current entry mechanics are withheld" in reason
               for reason in result["hard_failures"])


def test_non_actionable_audit_record_preserves_quality_without_false_failure():
    facts = quality_facts()
    facts.update(live_price=4.50, enriched_price=4.50, atr=0.70, float_m=8.0)
    result = validator.validate_ticket(
        "AUDIT",
        "SWING",
        {"structure": "PULLBACK_SWING", "mechanics_current": False},
        facts,
        technical_snapshot={"overall_freshness": "CURRENT"},
        ownership={"held": False},
    )

    assert result["state"] == "PASS"
    assert result["note"] == "no current mechanics claimed"
    assert result["quality_admission"]["state"] == "QUARANTINED"
