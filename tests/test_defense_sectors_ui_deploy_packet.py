from pathlib import Path


SCRIPT = Path("scripts/deploy_defense_sectors_ui_from_ref.sh").read_text()


def test_deploy_packet_requires_exact_reviewed_commit_and_ack():
    assert "DEFENSE_SECTORS_SHADOW_UI_ONLY" in SCRIPT
    assert "UI_SOURCE_REF" in SCRIPT
    assert "40-character commit SHA" in SCRIPT
    assert 'cat-file -e "$SOURCE_REF^{commit}"' in SCRIPT
    assert 'rev-parse "$SOURCE_REF^{commit}"' in SCRIPT


def test_deploy_packet_builds_from_git_objects_not_live_source():
    assert 'archive "$RESOLVED_COMMIT" apps/command-center-v3' in SCRIPT
    assert 'readonly HOST_REPO="${REPO:-$REPO_DEFAULT}"' in SCRIPT
    assert 'host_source_checkout|UNCHANGED' in SCRIPT
    for token in (
        "git checkout",
        "git switch",
        "git reset",
        "git clean",
        "git pull",
        "git merge",
        "git rebase",
    ):
        assert token not in SCRIPT.lower()


def test_deploy_packet_validates_decision_board_markers():
    for marker in (
        "Sector decision board",
        "ELIGIBLE NOW",
        "RESEARCH WATCH",
        "AVOID / REDUCE",
        "NO DECISION",
        "model critique only",
    ):
        assert marker in SCRIPT


def test_deploy_packet_changes_only_static_dist_with_backup():
    assert 'readonly LIVE_DIST="$LIVE_APP/dist"' in SCRIPT
    assert 'readonly BACKUP_ROOT=/home/johnclaw/tradeai-deploy-backups/command-center-v3' in SCRIPT
    assert 'mv "$LIVE_DIST" "$BACKUP_DIST"' in SCRIPT
    assert 'mv "$CANDIDATE" "$LIVE_DIST"' in SCRIPT
    assert 'rollback_live_dist|RESTORED' in SCRIPT
    assert 'service_restart|NONE_REQUIRED' in SCRIPT
    assert 'producer_activation|NONE' in SCRIPT
    assert 'database_write|NONE' in SCRIPT


def test_deploy_packet_has_no_service_or_trading_authority():
    for token in (
        "systemctl ",
        "service ",
        "sudo ",
        "docker run",
        "podman run",
        "psql ",
        "broker",
        "order",
        "2fa",
    ):
        assert token not in SCRIPT.lower()
