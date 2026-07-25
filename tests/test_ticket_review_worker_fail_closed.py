from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/run_ticket_review_job.py").read_text()


def test_worker_never_fakes_missing_validation_as_pass():
    assert 'validation or {"state": "PASS"}' not in SOURCE
    assert "selected = packet_quality.select_governing_validation(packet)" in SOURCE
    assert 'validation = selected.get("validation") or {}' in SOURCE
    assert 'deterministic = selected.get("deterministic") or "NOT_RUN"' in SOURCE


def test_worker_requires_explicit_admission_before_models():
    assert 'quality.get("state") == "ADMITTED"' in SOURCE
    assert 'quality.get("new_entry_allowed") is not False' in SOURCE
    assert 'if may_review and selected_lanes' in SOURCE
    assert 'if quality and (quality.get("state") != "ADMITTED"' not in SOURCE


def test_worker_has_no_paid_or_execution_authority():
    lowered = SOURCE.lower()
    assert '"paid_lane_called": false' in lowered
    for forbidden in (
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
        "premium_review(",
        "llm_lane.generate(",
    ):
        assert forbidden not in lowered


def test_worker_curates_packet_evidence_not_only_four_market_fields():
    for marker in (
        '"fundamentals": fundamentals',
        '"technical_state": packet.get("technical_state")',
        '"deterministic_thesis": packet.get("deterministic_thesis")',
        '"data_quality": packet.get("data_quality")',
        '"catalysts"',
    ):
        assert marker in SOURCE
