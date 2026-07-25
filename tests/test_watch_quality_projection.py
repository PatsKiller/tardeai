from pathlib import Path

from scripts import watch_quality_policy as policy
from scripts.watch_quality_projection import assemble_projection_facts


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/watch_quality_projection.py").read_text()


def test_projection_maps_existing_cache_fields_without_inventing_values():
    facts, technical, provenance = assemble_projection_facts(
        "TEST",
        watch_row={"price": 42.0, "rvol": 1.4, "last_seen_at": "2026-07-25T12:00:00+00:00"},
        packet={"facts": {"float_m": 85, "fundamentals": {"profit_margin_pct": 12}}},
        finviz={"atr": 2.1, "rsi": 54, "pe": 18, "pb": 3.2, "ps": 2.8, "cached_at": "2026-07-25T12:00:00+00:00"},
        supplement={"market_cap_b": 4.5, "quote_type": "EQUITY"},
    )

    assert facts["live_price"] == 42.0
    assert facts["float_m"] == 85.0
    assert facts["atr"] == 2.1
    assert facts["rvol"] == 1.4
    assert facts["fundamentals"]["market_cap_usd_millions"] == 4500.0
    assert facts["fundamentals"]["pe"] == 18.0
    assert facts["fundamentals"]["pb"] == 3.2
    assert facts["fundamentals"]["ps"] == 2.8
    assert technical["overall_freshness"] in {"PARTIAL", "UNKNOWN", "STALE"}
    assert set(provenance["observed_fields"]) >= {"price", "float_m", "market_cap_m", "atr", "pe", "pb", "ps"}


def test_projection_quarantines_low_price_and_extreme_volatility_even_without_ticket_write():
    facts, technical, _ = assemble_projection_facts(
        "JUNK",
        watch_row={"price": 4.0, "rvol": 3.5},
        packet={"facts": {"float_m": 8, "fundamentals": {"profit_margin_pct": -25}}},
        finviz={"atr": 0.7, "ps": 55, "cached_at": "2026-07-25T12:00:00+00:00"},
        supplement={"market_cap_b": 0.2, "quote_type": "EQUITY"},
    )

    result = policy.evaluate_admission(facts, technical_snapshot=technical, ticket={})
    assert result["state"] == "QUARANTINED"
    assert result["new_entry_allowed"] is False
    joined = " | ".join(result["hard_failures"])
    assert "below the $5.00 quality floor" in joined
    assert "low-float exclusion" in joined
    assert "extreme-volatility ceiling" in joined
    assert "pre-profit quality ceiling" in joined


def test_projection_treats_missing_evidence_as_research_only_not_admitted():
    facts, technical, _ = assemble_projection_facts(
        "UNKNOWN",
        watch_row={"price": 25.0},
        packet={},
        finviz={},
        supplement={"quote_type": "EQUITY"},
    )

    result = policy.evaluate_admission(facts, technical_snapshot=technical, ticket={})
    assert result["state"] == "RESEARCH_ONLY"
    assert result["new_entry_allowed"] is False
    assert result["warnings"]


def test_projection_source_is_read_only_and_offline():
    lowered = SOURCE.lower()
    for required in (
        "conn.set_session(readonly=true",
        "show transaction_read_only",
        '"database_write": false',
        '"packet_rebuild": false',
        '"cache_write": false',
        '"network_refresh": false',
        '"model_call": false',
        '"schedule_change": false',
        '"external_action": false',
        "watch-quality-projection-v1",
    ):
        assert required in lowered

    for forbidden in (
        "requests.get(",
        "requests.post(",
        "httpx.",
        "yfinance",
        "insert into",
        "update decision_packets",
        "delete from",
        "crontab ",
        "systemctl ",
        "subprocess.run",
    ):
        assert forbidden not in lowered
