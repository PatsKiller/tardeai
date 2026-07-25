from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = (ROOT / "scripts/watch_quality_gate3_sample_rebuild.py").read_text()
WRAPPER = (ROOT / "scripts/run_watch_quality_gate3_from_ref.sh").read_text()


def test_gate3_is_exactly_five_role_local_quant_sample():
    for marker in (
        'ROLE_ORDER = ("admitted", "research_only", "quarantined", "management_only", "contradiction")',
        'run_models=False',
        'PASS_GATE3_BOUNDED_LOCAL_REBUILD',
        'BLOCKED_GATE3_PREWRITE_MISMATCH',
        'BLOCKED_GATE3_PARTIAL_WRITE',
        'watch-quality-projection-v2',
        'packet_quality.apply_operator_presentation(packet)',
    ):
        assert marker in RUNNER


def test_gate3_prevalidates_every_candidate_before_persisting():
    evaluation = RUNNER.index('decision_service.evaluate(')
    prewrite = RUNNER.index('if prewrite_errors:')
    persist = RUNNER.index('decision_service.persist(')
    assert evaluation < prewrite < persist
    assert 'projected quality {expected_quality} != rebuilt quality {observed_quality}' in RUNNER


def test_gate3_has_no_model_scheduler_ui_or_execution_authority():
    lowered = RUNNER.lower()
    for forbidden in (
        'analysis_tier="standard_blind"',
        'analysis_tier="premium_review"',
        'llm_lane.generate',
        'crontab ',
        'systemctl ',
        'place_order',
        'broker_submit',
        'approve_order',
        '2fa_unlock',
        'deploy_defense_sectors',
    ):
        assert forbidden not in lowered
    for evidence in (
        '"model_provider_call": False',
        '"oauth_lane_call": False',
        '"paid_lane_call": False',
        '"schedule_change": False',
        '"service_restart": False',
        '"ui_deployment": False',
        '"proposal_or_execution_action": False',
    ):
        assert evidence in RUNNER


def test_gate3_wrapper_pins_source_and_preserves_dirty_checkout():
    for marker in (
        'WATCH_GATE3_EXECUTION_ACK',
        'EXECUTE_WATCH_QUALITY_GATE3',
        'WATCH_QUALITY_SOURCE_REF',
        'git -C "$HOST_REPO" archive "$RESOLVED_COMMIT" scripts config',
        'host_worktree_checkout|UNCHANGED',
        'WATCH_GATE3_ACK=BOUNDED_LOCAL_QUANT_SAMPLE',
        'final_status|PASS_GATE3_OPERATOR_PACKET',
    ):
        assert marker in WRAPPER
    for forbidden in ('git checkout', 'git reset', 'git clean', 'npm ', 'systemctl ', 'crontab '):
        assert forbidden not in WRAPPER
