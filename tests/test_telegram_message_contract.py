from __future__ import annotations

from scripts.lib.message_contract import (
    MESSAGE_REGISTRY,
    MessageEnvelope,
    classify_message,
    lint_registry,
    render_message,
    route_envelope,
)


def test_registry_is_complete_and_lintable():
    assert len(MESSAGE_REGISTRY) >= 16
    assert not lint_registry()
    assert {"unknown", "approval", "protection_risk", "platform_availability"} <= set(MESSAGE_REGISTRY)


def test_typed_envelope_renders_required_fields_and_missing_values_honestly():
    envelope = MessageEnvelope(
        message_type="entry_watch",
        producer="entry_planner",
        primary_symbols=("AAPL",),
        facts={"status": "BUY READY", "price": 210.0},
        operator_action="Review entry zone",
        evidence=("research id=abc",),
    )
    rendered = render_message(envelope)
    assert "AAPL" in rendered.text
    assert "210.0" in rendered.text
    assert "not available" in rendered.text
    assert "research id=abc" in rendered.text
    assert "<blockquote expandable>" in rendered.text
    assert route_envelope(envelope)["policy_decision"] == "deterministic_registry"


def test_unknown_message_is_safe_and_non_interruptive():
    envelope = classify_message("a novel producer payload with no known contract", producer="new_worker")
    rendered = render_message(envelope)
    assert envelope.message_type == "unknown"
    assert route_envelope(envelope)["route_mode"] == "COMMAND_CENTER"
    assert "Unclassified platform message" in rendered.text
    assert "not available" in rendered.text
    assert "novel producer payload" in rendered.text


def test_legacy_known_messages_are_classified_before_route():
    envelope = classify_message("[PLATFORM_AVAILABILITY] quotes unavailable", producer="quote_worker")
    assert envelope.message_type == "platform_availability"
    assert route_envelope(envelope)["route_mode"] == "IMMEDIATE"


def test_utf16_parts_stay_within_telegram_limit_and_diagnostics_are_collapsed():
    envelope = MessageEnvelope(
        message_type="research", producer="research", facts={"state": "completed"},
        diagnostics=("📈" * 5000,),
    )
    rendered = render_message(envelope)
    assert len(rendered.parts) > 1
    assert all(len(part.encode("utf-16-le")) // 2 <= 4096 for part in rendered.parts)
    assert any("split at paragraph boundary" in warning for warning in rendered.warnings)
