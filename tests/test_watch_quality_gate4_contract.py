from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = (ROOT / "scripts/watch_quality_gate4_verify.py").read_text()
WRAPPER = (ROOT / "scripts/run_watch_quality_gate4_from_ref.sh").read_text()


def test_gate4_requires_passing_gate3_and_exact_five_roles():
    for marker in (
        'watch-quality-gate3-sample-rebuild-v1',
        'PASS_GATE3_BOUNDED_LOCAL_REBUILD',
        '"admitted", "research_only", "quarantined", "management_only", "contradiction"',
        'watch-quality-gate4-readonly-verification-v1',
        'PASS_GATE4_READONLY_VERIFICATION',
        'BLOCKED_GATE4_VERIFICATION',
    ):
        assert marker in RUNNER


def test_gate4_verifies_hash_quality_source_and_presentation():
    for marker in (
        'latest packet hash differs from Gate 3 readback',
        'live packet quality differs from projected Gate 3 role',
        'live packet has no canonical validation source',
        'watch-quality-governance-v1 presentation',
        'one sovereign decision',
        'presentation_conflicts(packet)',
        'quality_audit.build_report',
    ):
        assert marker in RUNNER


def test_gate4_is_forced_readonly_and_has_no_rollout_authority():
    for marker in (
        'conn.set_session(readonly=True, autocommit=False)',
        'SHOW transaction_read_only',
        '"database_write": False',
        '"packet_rebuild": False',
        '"model_provider_call": False',
        '"schedule_change": False',
        '"ui_deployment": False',
        '"proposal_or_execution_action": False',
    ):
        assert marker in RUNNER
    lowered = RUNNER.lower()
    for forbidden in (
        'insert into',
        'update decision_packets',
        'delete from',
        'decision_service.persist',
        'llm_lane',
        'crontab ',
        'systemctl ',
        'place_order',
        'broker_submit',
    ):
        assert forbidden not in lowered


def test_gate4_wrapper_pins_source_and_requires_passing_evidence():
    for marker in (
        'WATCH_GATE4_EXECUTION_ACK',
        'VERIFY_WATCH_QUALITY_GATE4',
        'WATCH_QUALITY_SOURCE_REF',
        'PASS_GATE3_BOUNDED_LOCAL_REBUILD',
        'git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" scripts config',
        'host_worktree_checkout|UNCHANGED',
        'final_status|PASS_GATE4_OPERATOR_PACKET',
    ):
        assert marker in WRAPPER
    for forbidden in ('git checkout', 'git reset', 'git clean', 'npm ', 'systemctl ', 'crontab '):
        assert forbidden not in WRAPPER
