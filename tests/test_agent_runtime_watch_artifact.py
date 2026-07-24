from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.agent_runtime.sentinel import finding_codes, inspect_ticket
from scripts.agent_runtime.watch_artifact import WATCH_ARTIFACT_VERSION, WatchArtifactError, adapt_watch_item


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)


def valid_watch_item():
    return {
        "id": "watch-123",
        "symbol": "SCHG",
        "starred": True,
        "profile_sector": "Large Blend",
        "catalyst_headline": "No near-term catalyst recorded",
        "price": 33.40,
        "rsi": 45.3,
        "trend_state": "neutral",
        "last_enriched_at": "2026-07-23T13:30:00+00:00",
        "origin_system": "operator_watch",
        "flags": {"growth": True, "dividend": True},
        "decision_packet": {
            "packet_id": "packet-456",
            "current_input_snapshot": {
                "price": 33.40,
                "rsi": 45.3,
                "regime": "risk_off",
            },
            "current_actionable_plan": {
                "state": "READY",
                "ticket_validation": {
                    "state": "PASS",
                    "proposal_allowed": True,
                    "hard_failures": [],
                    "source": "deterministic-watch-validator",
                },
                "mechanics": {
                    "entry_low": 34.09,
                    "entry_high": 34.15,
                    "limit": 34.12,
                    "stop": 33.66,
                    "target": 35.50,
                    "risk_reward_ratio": 2.8,
                    "direction": "LONG",
                    "trigger": "Wait for pullback",
                },
            },
        },
    }


def test_watch_adapter_builds_hash_bound_advisory_artifact() -> None:
    result = adapt_watch_item(valid_watch_item(), now=NOW)
    artifact = result.artifact
    assert artifact.artifact_version == WATCH_ARTIFACT_VERSION
    assert artifact.symbol == "SCHG"
    assert artifact.state == "READY"
    assert artifact.direction == "LONG"
    assert artifact.advisory_only is True
    assert artifact.financial_authority == "DENIED"
    assert artifact.input_hash_origin == "adapter-canonical-input-snapshot"
    assert artifact.validation_hash_origin == "adapter-canonical-validation"
    assert len(artifact.input_hash) == 64
    assert len(artifact.validation_hash) == 64
    assert len(artifact.artifact_hash) == 64
    assert artifact.source_refs == ("watch:SCHG", "source:watch-123", "source:packet-456")
    assert artifact.market_context["price"] == 33.40
    assert artifact.market_context["rsi"] == 45.3
    assert artifact.strategy_context["flags"] == ["DIVIDEND", "GROWTH"]
    assert result.source_validation["state"] == "PASS"


def test_watch_adapter_output_passes_clean_sentinel_kernel() -> None:
    result = adapt_watch_item(valid_watch_item(), now=NOW)
    report = inspect_ticket(result.artifact.sentinel_ticket(), result.source_validation, now=NOW)
    assert report.verdict == "PASS"
    assert report.release_allowed is True
    assert report.findings == ()


def test_source_hashes_are_preserved_when_valid() -> None:
    raw = valid_watch_item()
    raw["input_hash"] = "b" * 64
    raw["validation_hash"] = "a" * 64
    artifact = adapt_watch_item(raw, now=NOW).artifact
    assert artifact.input_hash == "b" * 64
    assert artifact.validation_hash == "a" * 64
    assert artifact.input_hash_origin == "source"
    assert artifact.validation_hash_origin == "source"


def test_nonactionable_source_mechanics_are_preserved_for_sentinel_to_block() -> None:
    raw = valid_watch_item()
    raw["decision_packet"]["current_actionable_plan"]["state"] = "NO_TRADE"
    raw["decision_packet"]["current_actionable_plan"]["ticket_validation"]["proposal_allowed"] = False
    result = adapt_watch_item(raw, now=NOW)
    report = inspect_ticket(result.artifact.sentinel_ticket(), result.source_validation, now=NOW)
    assert report.release_allowed is False
    assert "MECHANICS_EXPOSED_FOR_NONACTIONABLE_STATE" in finding_codes(report)


def test_nested_input_snapshot_is_a_valid_market_fallback() -> None:
    raw = valid_watch_item()
    raw.pop("price")
    raw.pop("rsi")
    artifact = adapt_watch_item(raw, now=NOW).artifact
    assert artifact.market_context["price"] == 33.40
    assert artifact.market_context["rsi"] == 45.3
    assert "price unavailable" not in artifact.data_gaps
    assert "rsi unavailable" not in artifact.data_gaps


def test_missing_market_fields_are_truthful_data_gaps() -> None:
    raw = valid_watch_item()
    raw.pop("price")
    raw.pop("rsi")
    raw.pop("profile_sector")
    raw["decision_packet"]["current_input_snapshot"].pop("price")
    raw["decision_packet"]["current_input_snapshot"].pop("rsi")
    artifact = adapt_watch_item(raw, now=NOW).artifact
    assert "price unavailable" in artifact.data_gaps
    assert "rsi unavailable" in artifact.data_gaps
    assert "sector unavailable" in artifact.data_gaps


@pytest.mark.parametrize(
    "authority",
    [
        {"broker_action": {"type": "submit"}},
        {"order_payload": {"side": "buy"}},
        {"authorization": {"state": "armed"}},
        {"two_factor": {"state": "live"}},
        {"credentials": {"user": "fixture"}},
    ],
)
def test_financial_authority_material_is_rejected(authority) -> None:
    raw = valid_watch_item()
    raw.update(authority)
    with pytest.raises(WatchArtifactError, match="authority material"):
        adapt_watch_item(raw, now=NOW)


def test_secret_like_material_is_rejected_even_when_nested() -> None:
    raw = valid_watch_item()
    raw["metadata"] = {"password": "must-not-enter-agent-context"}
    with pytest.raises(WatchArtifactError, match="authority material"):
        adapt_watch_item(raw, now=NOW)


def test_invalid_as_of_is_rejected_not_silently_replaced() -> None:
    raw = valid_watch_item()
    raw["last_enriched_at"] = "not-a-time"
    with pytest.raises(WatchArtifactError, match="invalid Watch as-of"):
        adapt_watch_item(raw, now=NOW)
