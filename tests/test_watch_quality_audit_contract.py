from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/watch_quality_audit.py").read_text()


def test_audit_forces_database_read_only_mode():
    assert "conn.set_session(readonly=True, autocommit=False)" in SOURCE
    assert 'cur.execute("SHOW transaction_read_only")' in SOURCE
    assert 'raise RuntimeError("database session is not read-only")' in SOURCE
    assert "conn.rollback()" in SOURCE


def test_audit_uses_ranked_population_and_canonical_packet_gate():
    assert "min(hermes_rank)" in SOURCE
    assert "packet_quality.packet_gate" in SOURCE
    assert "packet_quality.presentation_conflicts" in SOURCE
    for state in ("ADMITTED", "UNASSESSED", "RESEARCH_ONLY", "QUARANTINED"):
        assert state in (Path(__file__).resolve().parents[1] / "scripts/watch_packet_quality.py").read_text()


def test_audit_has_no_refresh_model_schedule_or_trading_authority():
    lowered = SOURCE.lower()
    for forbidden in (
        "insert into",
        "update decision_packets",
        "delete from",
        "enqueue_run(",
        "run_free_reviews(",
        "llm_lane",
        "local_llm",
        "crontab",
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
    ):
        assert forbidden not in lowered


def test_audit_output_is_sanitized_and_private_when_saved():
    assert 'public_report = {key: value for key, value in report.items() if key != "all_rows"}' in SOURCE
    assert "path.chmod(0o600)" in SOURCE
    assert '"database_write": False' in SOURCE
    assert '"model_call": False' in SOURCE
    assert '"schedule_change": False' in SOURCE
