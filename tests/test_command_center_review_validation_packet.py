from pathlib import Path


SCRIPT = Path("scripts/validate_command_center_global_review_from_ref.sh").read_text()


def test_validation_packet_is_exact_ref_and_temporary_only():
    for token in (
        "COMMAND_CENTER_REVIEW_VALIDATION_ONLY",
        "40-character commit SHA",
        'cat-file -e "$SOURCE_REF^{commit}"',
        'archive "$RESOLVED_COMMIT"',
        "mktemp -d /tmp/command-center-review-validation",
        "TEMPORARY_BUILD_AND_BROWSER_TESTS_ONLY",
        "live_dist_change|NONE",
        "final_status|PASS_COMMAND_CENTER_REVIEW_VALIDATION",
    ):
        assert token in SCRIPT


def test_validation_packet_runs_build_and_modal_browser_contract():
    for token in (
        '"$NPM" ci',
        '"$NPX" tsc --pretty false',
        '"$NPX" vite build',
        "playwright install chromium",
        "e2e/defense-sectors-interactions.spec.ts",
        "e2e/global-review-modal.spec.ts",
        "command-center-global-review-v1",
        "URL-addressable decision, provenance and evidence review",
    ):
        assert token in SCRIPT


def test_validation_packet_has_no_live_or_trading_authority():
    lowered = SCRIPT.lower()
    for token in (
        'mv "$candidate" "$live_dist"',
        'mv "$live_dist"',
        "systemctl ",
        "service ",
        "sudo ",
        "psql ",
        "broker_submit",
        "place_order",
        "approve_order",
        "2fa_unlock",
    ):
        assert token not in lowered
    for evidence in (
        "service_restart|NONE",
        "producer_activation|NONE",
        "database_write|NONE",
        "broker_or_order_action|NONE",
    ):
        assert evidence in SCRIPT
