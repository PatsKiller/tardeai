from pathlib import Path

from scripts import watch_quality_policy as policy
from scripts.watch_quality_projection_v2 import assemble_projection_facts


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/watch_quality_projection_v2.py").read_text()


def _base_packet(**fundamentals):
    return {
        "facts": {
            "atr": 1.5,
            "sma50": 20.0,
            "fundamentals": {
                "profit_margin_pct": 12.0,
                "shares_outstanding_m": 100.0,
                **fundamentals,
            },
        },
        "technical_snapshot": {"overall_freshness": "CURRENT"},
    }


def test_finviz_market_cap_suffix_is_mislabeled_millions_not_billions():
    facts, _, provenance = assemble_projection_facts(
        "FINVIZ",
        watch_row={"price": 10.0, "float_m": 80.0, "rvol": 1.1},
        packet=_base_packet(shares_outstanding_m=100.0),
        finviz={"market_cap_b": 950.0, "pe": 18.0, "cached_at": "2026-07-25T12:00:00+00:00"},
        supplement={"market_cap_b": 9.5},
    )

    assert facts["fundamentals"]["market_cap_usd_millions"] == 950.0
    assert provenance["field_sources"]["market_cap_usd_millions"] == (
        "finviz:market_cap_b_mislabeled_millions"
    )


def test_supplement_market_cap_suffix_remains_true_billions():
    facts, _, provenance = assemble_projection_facts(
        "SUPP",
        watch_row={"price": 45.0, "float_m": 90.0, "rvol": 1.0},
        packet=_base_packet(shares_outstanding_m=100.0),
        finviz={"pe": 20.0},
        supplement={"market_cap_b": 4.5, "quote_type": "EQUITY"},
    )

    assert facts["fundamentals"]["market_cap_usd_millions"] == 4500.0
    assert provenance["field_sources"]["market_cap_usd_millions"] == (
        "supplement:market_cap_b_true_billions"
    )


def test_current_watch_price_beats_stale_packet_copy():
    facts, _, provenance = assemble_projection_facts(
        "CURRENT",
        watch_row={"price": 42.0, "float_m": 75.0, "rvol": 1.4},
        packet={
            "facts": {
                "live_price": 30.0,
                "float_m": 60.0,
                "rvol": 0.7,
                "atr": 2.0,
                "fundamentals": {
                    "market_cap_usd_millions": 3150.0,
                    "profit_margin_pct": 10.0,
                    "shares_outstanding_m": 75.0,
                },
            },
            "technical_snapshot": {"overall_freshness": "CURRENT"},
        },
        finviz={"pe": 18.0},
        supplement={},
    )

    assert facts["live_price"] == 42.0
    assert facts["float_m"] == 75.0
    assert facts["rvol"] == 1.4
    assert provenance["field_sources"]["price"] == "watch_row:price"


def test_absurd_margin_is_rejected_not_used_as_fundamental_truth():
    facts, technical, provenance = assemble_projection_facts(
        "BADMARGIN",
        watch_row={"price": 25.0, "float_m": 100.0, "rvol": 1.0},
        packet={
            "facts": {
                "atr": 1.0,
                "sma50": 24.0,
                "fundamentals": {"shares_outstanding_m": 100.0},
            },
            "technical_snapshot": {"overall_freshness": "CURRENT"},
        },
        finviz={
            "market_cap_b": 2500.0,
            "profit_margin_pct": -8550.65,
            "pe": 15.0,
            "ps": 2.0,
        },
        supplement={},
    )

    assert "profit_margin_pct" not in facts["fundamentals"]
    assert "profit_margin_pct" in provenance["rejected_fields"]
    result = policy.evaluate_admission(facts, technical_snapshot=technical, ticket={})
    assert result["state"] != "ADMITTED"
    assert result["new_entry_allowed"] is False


def test_market_cap_conflict_is_withheld_instead_of_driving_admission():
    facts, technical, provenance = assemble_projection_facts(
        "CONFLICT",
        # Keep ATR at 6% so this test isolates the market-cap conflict instead of
        # also triggering the independent 10% extreme-volatility quarantine.
        watch_row={"price": 25.0, "float_m": 90.0, "rvol": 1.0},
        packet=_base_packet(shares_outstanding_m=100.0),
        finviz={"market_cap_b": 250000.0, "pe": 18.0},
        supplement={},
    )

    assert "market_cap_usd_millions" not in facts["fundamentals"]
    assert "market_cap_usd_millions" in provenance["rejected_fields"]
    result = policy.evaluate_admission(facts, technical_snapshot=technical, ticket={})
    assert result["state"] == "RESEARCH_ONLY"
    assert result["new_entry_allowed"] is False


def test_projection_v2_remains_offline_and_read_only_by_construction():
    lowered = SOURCE.lower()
    for required in (
        "watch-quality-projection-v2",
        "market_cap_b_mislabeled_millions",
        "market_cap_b_true_billions",
        "projection_v1.assemble_projection_facts = assemble_projection_facts",
        "no packet, cache, database, provider, schedule, service, model, broker, order",
    ):
        assert required in lowered

    for forbidden in (
        "requests.get(",
        "requests.post(",
        "httpx.",
        "import yfinance",
        "yf.ticker(",
        "insert into",
        "update decision_packets",
        "delete from",
        "crontab ",
        "systemctl ",
        "subprocess.run",
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
    ):
        assert forbidden not in lowered
