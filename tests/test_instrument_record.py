from scripts.lib.instrument_record import build_instrument_record, notification_crossed, validate_instrument_record


def test_record_normalizes_existing_sources_without_fake_identity():
    rec = build_instrument_record(
        {"symbol": "schd", "synthesis_narrative": "watch", "notification_priority": "HIGH"},
        identity={"security_guid": "sec-1", "issuer_guid": "iss-1", "sector_id": "sector-fin"},
        research={"research_ids": ["res-1"], "next_eligible_at": "2026-09-01T12:00:00Z"},
        artifacts=[{"artifact_id": "art-1"}],
        operator_turns=[{"turn_id": "turn-1"}],
        lessons=[{"lesson_id": "lesson-1"}],
        workflow_id="wf-1",
    )
    assert rec["schema"] == "InstrumentRecord@v1"
    assert rec["symbol"] == "SCHD"
    assert rec["security_id"] == "sec-1"
    assert rec["workflow_id"] == "wf-1"
    assert rec["artifact_ids"] == ["art-1"]
    assert rec["operator_turn_ids"] == ["turn-1"]
    assert rec["lesson_ids"] == ["lesson-1"]
    assert validate_instrument_record(rec) == []


def test_record_degrades_when_identity_is_missing():
    rec = build_instrument_record({"symbol": "ABC", "thesis": "legacy"})
    assert rec["data_quality"] == "LEGACY"
    assert "canonical_identity_missing" in validate_instrument_record(rec)


def test_notification_only_crosses_upward():
    assert notification_crossed("LOW", "HIGH") is True
    assert notification_crossed("HIGH", "HIGH") is False
    assert notification_crossed("CRITICAL", "LOW") is False


def test_record_has_stable_projection_keys():
    rec = build_instrument_record({"symbol": "V", "canonical_entity_id": "sec-v"}, workflow_id="wf-v")
    for key in ("thesis", "cc_narrative", "last_event", "last_price_hash", "research_ids",
                "artifact_ids", "operator_turn_ids", "lesson_ids", "next_eligible_at",
                "notify_priority", "workflow_id"):
        assert key in rec
