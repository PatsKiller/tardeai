from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = (ROOT / "scripts/watch_quality_local_scheduler.py").read_text()
RUNNER = (ROOT / "scripts/run_watch_quality_local_scheduler_from_ref.sh").read_text()
INSTALLER = (ROOT / "scripts/install_watch_quality_local_scheduler_from_ref.sh").read_text()


def test_gate6_scheduler_withholds_all_model_lanes():
    for marker in (
        'watch-quality-local-scheduler-v1',
        'analysis_tier": "LOCAL_QUANT"',
        '"model_provider_call": False',
        '"oauth_lane_call": False',
        '"paid_lane_call": False',
        'selected_model_lane_calls": 0',
        'oauth_withheld',
        'watch-quality-projection-v2',
        'watch-quality-governed-builder-v1',
        'governed_builder.build_packet(',
        'decision_service.persist(',
        'PASS_LOCAL_SCHEDULER_COMPLETED',
    ):
        assert marker in SCHEDULER
    lowered = SCHEDULER.lower()
    for forbidden in (
        'analysis_tier="standard_blind"',
        'analysis_tier="premium_review"',
        'llm_lane.generate',
        'enqueue_run(',
        'spawn_workers=true',
        'place_order',
        'broker_submit',
        'approve_order',
        '2fa_unlock',
    ):
        assert forbidden not in lowered


def test_gate6_dry_run_precedes_activation_and_is_bounded():
    for marker in (
        'DEFAULT_LIMIT = 20',
        'MAX_LIMIT = 40',
        'PROJECTION_LIMIT = 200',
        '--dry-run',
        '--run',
        'WATCH_QUALITY_LOCAL_SCHEDULER_ACK',
        'ACTIVATE_BOUNDED_LOCAL_QUANT',
        'WATCH_SCHEDULER_PAUSED',
        'WATCH_QUALITY_SOURCE_COMMIT',
    ):
        assert marker in SCHEDULER


def test_gate6_exact_ref_runner_requires_gate4_live_gate5_and_zero_models():
    for marker in (
        'WATCH_QUALITY_SOURCE_REF',
        'PASS_GATE4_READONLY_VERIFICATION',
        'build-meta.json',
        'live UI source commit differs from scheduler source',
        'watch-quality-governance-v1',
        'WATCH_QUALITY_SCHEDULER_MODE',
        'WATCH_QUALITY_SOURCE_COMMIT="$RESOLVED_COMMIT"',
        'governed_builder|watch-quality-governed-builder-v1',
        'SHADOW_DISABLE_MODELS=1',
        'SHADOW_DISABLE_TICKET_CRITIC=1',
        'blind_model_system|DISABLED',
        'inline_ticket_critic|DISABLED',
        'oauth_lane|WITHHELD',
        'paid_lane|WITHHELD',
    ):
        assert marker in RUNNER


def test_gate6_installer_backs_up_crontab_and_refuses_conflicts():
    for marker in (
        'INSTALL_AND_RUN_BOUNDED_LOCAL_QUANT',
        '.crontab_backup_watch_quality_',
        'flock -n',
        '17 7 * * *',
        'BLOCKED_GATE6_CONFLICTING_WATCH_SCHEDULE',
        'watch_decision_scheduler|watch_decision_refresh|watch-quality-local-|watch_quality_local_scheduler',
        'PASS_GATE6_LOCAL_SCHEDULER_ACTIVATION',
        'oauth_lane|WITHHELD',
        'paid_lane|WITHHELD',
    ):
        assert marker in INSTALLER
    assert INSTALLER.index('WATCH_QUALITY_SCHEDULER_MODE=DRY_RUN') < INSTALLER.index('crontab "$CURRENT"')
