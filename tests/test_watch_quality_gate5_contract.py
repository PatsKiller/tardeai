from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "scripts/deploy_watch_quality_ui_from_ref.sh").read_text()


def test_gate5_requires_exact_source_and_passing_readonly_gate4():
    for marker in (
        "WATCH_QUALITY_SHADOW_UI_ONLY",
        "WATCH_QUALITY_SOURCE_REF",
        "exact 40-character commit SHA",
        'cat-file -e "$SOURCE_REF^{commit}"',
        'PASS_GATE4_READONLY_VERIFICATION',
        '"read_only": true',
    ):
        assert marker in SOURCE


def test_gate5_builds_and_checks_watch_governance_markers():
    for marker in (
        '"$NPM" ci',
        '"$NPX" tsc --pretty false',
        '"$NPX" vite build',
        'watch-quality-governance-v1',
        'STREET DATA >7D',
        'OWNERSHIP ELIGIBLE',
        'MECHANICS VALID',
        'DETERMINISTIC_REVIEW_REQUIRED',
        'RECOMMENDED · NOT RUN',
        'command-center-global-review-v1',
        'command-center-structured-provenance-v1',
    ):
        assert marker in SOURCE


def test_gate5_is_atomic_with_backup_and_rollback_evidence():
    for marker in (
        'BACKUP_ROOT=/home/johnclaw/tradeai-deploy-backups/command-center-v3',
        'mv "$LIVE_DIST" "$BACKUP_DIST"',
        'mv "$CANDIDATE" "$LIVE_DIST"',
        'rollback_live_dist|RESTORED',
        'host_source_checkout|UNCHANGED',
        'final_status|PASS_GATE5_WATCH_UI_DEPLOY',
    ):
        assert marker in SOURCE


def test_gate5_has_no_backend_scheduler_model_or_database_authority():
    for marker in (
        'backend_change|NONE',
        'scheduler_activation|NONE',
        'model_provider_call|NONE',
        'database_write|NONE',
        'service_restart|NONE_REQUIRED',
    ):
        assert marker in SOURCE
    lowered = SOURCE.lower()
    for forbidden in (
        'psql ',
        'crontab ',
        'systemctl ',
        'llm_lane',
        'place_order',
        'broker_submit',
        'approve_order',
        '2fa_unlock',
    ):
        assert forbidden not in lowered
