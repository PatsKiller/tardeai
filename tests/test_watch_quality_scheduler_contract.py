from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/watch_decision_scheduler.py").read_text()


def test_scheduler_uses_canonical_packet_quality_extraction():
    assert "import watch_packet_quality as packet_quality" in SOURCE
    assert "packet_quality.packet_gate" in SOURCE
    assert "def _packet_gate" not in SOURCE


def test_oauth_blind_requires_admitted_deterministic_pass():
    for marker in (
        'quality_state == "ADMITTED"',
        'gate["new_entry_allowed"] is not False',
        'gate["deterministic"] == "PASS"',
        'analysis_tier="STANDARD_BLIND"',
        'reason="admitted_quality_blind_cadence"',
    ):
        assert marker in SOURCE


def test_nonheld_quarantined_names_are_deferred_from_active_budget():
    assert 'quality_state == "QUARANTINED" and not held_or_starred' in SOURCE
    assert 'plan["quality_deferred"]' in SOURCE
    assert 'quality_deferred' in SOURCE


def test_local_deterministic_rebuild_precedes_any_model_lane():
    assert "QUALITY_UNASSESSED — rebuild locally before any model lane" in SOURCE
    assert 'analysis_tier="LOCAL_QUANT"' in SOURCE
    assert "local deterministic first; OAuth only after ADMITTED + PASS" in SOURCE


def test_scheduler_never_schedules_premium_or_execution():
    lowered = SOURCE.lower()
    for forbidden in (
        'analysis_tier="premium_review"',
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
        "paid_lane_called",
    ):
        assert forbidden not in lowered
    assert '"paid_cost_usd": 0' in SOURCE
