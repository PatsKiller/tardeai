from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "moomoo" / "install_gateway_user_proof.sh"
UNIT = (
    ROOT
    / "config"
    / "systemd"
    / "user"
    / "tradeai-moomoo-l2-gateway-proof.service"
)
CONFIG = ROOT / "config" / "moomoo_l2_gateway.example.yaml"
RUNBOOK = ROOT / "docs" / "runbooks" / "MOOMOO_L2_GATEWAY_USER_PROOF.md"


def test_user_proof_installer_is_exact_sha_and_fail_closed() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert 'git -C "$REPO" rev-parse --git-dir' in text
    assert 'git fetch origin "$BRANCH:refs/remotes/origin/$BRANCH"' in text
    assert "git rev-parse \"origin/$BRANCH\"" in text
    assert "git archive \"$EXPECTED_SHA\"" in text
    assert "TRADEAI_SOURCE_COMMIT=%s" in text
    assert "grep -Fx 'enabled: false'" in text
    assert 'rm -f "$CONFIG_ROOT/ENABLE_MOOMOO_L2_GATEWAY_PROOF"' in text
    assert 'systemctl --user disable --now "$UNIT_NAME"' in text
    assert "git checkout" not in text
    assert "git switch" not in text
    assert "git reset" not in text
    assert "systemctl --user enable" not in text
    assert "sudo" not in text
    assert "place_order" not in text
    assert "unlock_trade" not in text


def test_user_proof_unit_has_user_scoped_activation_and_read_only_entrypoint() -> None:
    text = UNIT.read_text(encoding="utf-8")

    assert "ConditionPathExists=%h/.config/tradeai/ENABLE_MOOMOO_L2_GATEWAY_PROOF" in text
    assert "EnvironmentFile=%h/.config/tradeai/moomoo_l2_gateway_proof.env" in text
    assert "gateway_service.py --config" in text
    assert "ReadWritePaths=%h/.tradeai/runtime" in text
    assert "WantedBy=default.target" in text
    assert "User=" not in text
    assert "place_order" not in text
    assert "unlock_trade" not in text


def test_user_proof_ships_disabled_and_documents_separate_activation() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    runbook = RUNBOOK.read_text(encoding="utf-8")

    assert "enabled: false" in config
    assert "The installer never creates that marker." in runbook
    assert 'git show "$EXPECTED_SHA:scripts/moomoo/install_gateway_user_proof.sh"' in runbook
    assert "production checkout branch, index, and working tree are not changed" in runbook
    assert "Explicit data-only activation" in runbook
    assert "zero order, trade-unlock, session, 2FA, database-write, or LLM authority" in runbook
