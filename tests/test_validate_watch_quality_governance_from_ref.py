from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "scripts/validate_watch_quality_governance_from_ref.sh").read_text()


def test_validator_requires_ack_and_exact_commit():
    for marker in (
        "WATCH_QUALITY_VALIDATION_ONLY",
        "WATCH_QUALITY_SOURCE_REF",
        "exact 40-character commit SHA",
        'cat-file -e "$SOURCE_REF^{commit}"',
        'rev-parse "$SOURCE_REF^{commit}"',
        'archive "$RESOLVED_COMMIT"',
    ):
        assert marker in SOURCE


def test_validator_builds_from_temporary_git_archive_only():
    assert "mktemp -d /tmp/watch-quality-validation" in SOURCE
    assert "TEMPORARY_BUILD_AND_TESTS_ONLY" in SOURCE
    assert 'live_dist_change|NONE' in SOURCE
    for forbidden in (
        "git checkout",
        "git switch",
        "git reset",
        "git clean",
        "git pull",
        "git merge",
        "git rebase",
    ):
        assert forbidden not in SOURCE.lower()


def test_validator_runs_focused_python_and_ui_gates():
    for marker in (
        "scripts/watch_quality_policy.py",
        "scripts/watch_packet_quality.py",
        "scripts/watch_quality_projection.py",
        "scripts/watch_quality_projection_v2.py",
        "scripts/watch_quality_governed_builder.py",
        "scripts/watch_quality_gate3_sample_rebuild.py",
        "scripts/watch_quality_gate4_verify.py",
        "scripts/watch_quality_local_scheduler.py",
        "scripts/strategy_ticket_validator.py",
        "scripts/strategy_ticket_review.py",
        "scripts/strategy_ticket_reconciler.py",
        "scripts/watch_decision_scheduler.py",
        "scripts/watch_quality_audit.py",
        "scripts/research_due_diligence.py",
        "scripts/specialized_research_due_diligence.py",
        "scripts/specialized_research_pipeline.py",
        "scripts/sector_momentum_engine_v5.py",
        "test_watch_quality_policy.py",
        "test_watch_packet_quality.py",
        "test_watch_quality_projection.py",
        "test_watch_quality_projection_v2.py",
        "test_watch_quality_gate3_contract.py",
        "test_watch_quality_gate4_contract.py",
        "test_watch_quality_gate5_contract.py",
        "test_watch_quality_gate6_contract.py",
        "test_research_due_diligence.py",
        '"$NPX" tsc --pretty false',
        '"$NPX" vite build',
        "watch-quality-governance-v1",
        "watch-quality-projection-v2",
        "watch-quality-governed-builder-v1",
        "watch-quality-gate3-sample-rebuild-v1",
        "watch-quality-gate4-readonly-verification-v1",
        "WATCH_QUALITY_SHADOW_UI_ONLY",
        "watch-quality-local-scheduler-v1",
        "SUPERSEDED_SOURCE_UNIT_CONFLICT",
        "research-due-diligence-v1",
        "PROPOSAL,DEFENSE,SECTOR,INDUSTRY,WATCH",
        "STREET DATA >7D",
        "OWNERSHIP ELIGIBLE",
        "MECHANICS VALID",
    ):
        assert marker in SOURCE


def test_validator_has_no_live_database_provider_schedule_or_external_authority():
    lowered = SOURCE.lower()
    for forbidden in (
        'mv "$candidate"',
        'mv "$live_dist"',
        "systemctl ",
        "service ",
        "sudo ",
        "psql ",
        "crontab ",
        "llm_lane",
        "local_llm",
        "place_order",
        "broker_submit",
        "approve_order",
        "2fa_unlock",
    ):
        assert forbidden not in lowered
    for evidence in (
        "database_write|NONE",
        "packet_rebuild|NONE",
        "model_provider_call|NONE",
        "paid_lane_call|NONE",
        "schedule_change|NONE",
        "service_restart|NONE",
        "external_action|NONE",
        "PASS_WATCH_QUALITY_GOVERNANCE_VALIDATION",
    ):
        assert evidence in SOURCE
