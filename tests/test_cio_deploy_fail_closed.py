"""P1-3 — deploy scripts fail closed on integrity / health; no stale PR pin."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PHASE2 = ROOT / "scripts" / "cio_phase2_exact_main_deploy.sh"
PORT = ROOT / "scripts" / "deploy_portfolio_server.sh"


def test_phase2_integrity_hook_is_hard_fail():
    src = PHASE2.read_text(encoding="utf-8")
    assert "run_integrity_hook" in src
    assert "generate_integrity_manifest.py" in src
    assert "refuse to continue" in src
    assert "TRADEAI_CC_SOURCE_PR=cio-phase2-exact-main" not in src
    assert "TRADEAI_CC_SOURCE_PR=296" not in src
    assert "TRADEAI_CC_DEPLOYED_SHA=" in src
    assert "CIO_SOURCE_PR" in src
    assert "write_deploy_receipt" in src
    assert "rolling back to" in src
    assert "not claiming promote OK" in src


def test_phase2_overlays_complete_reviewed_tree_without_runtime_or_secrets():
    src = PHASE2.read_text(encoding="utf-8")
    overlay = src.split("overlay_main() {", 1)[1].split("write_systemd() {", 1)[0]

    assert '"${ROOT}/" "${dest}/"' in overlay
    assert "rsync -a --delete" in overlay
    assert '"${ROOT}/scripts/" "${dest}/scripts/"' not in overlay
    assert "--exclude='data/'" in overlay
    assert "--exclude='state/'" in overlay
    assert "--exclude='logs/'" in overlay
    assert "--exclude='apps/command-center-v3/dist/'" in overlay
    assert "--exclude='.env'" in overlay
    assert "--exclude='config/broker_credentials.env'" in overlay


def test_portfolio_deploy_integrity_and_health_fail_closed():
    src = PORT.read_text(encoding="utf-8")
    assert "generate_integrity_manifest.py" in src
    assert "refuse to continue" not in src or "Integrity manifest generation failed" in src
    assert "WARNING: Integrity manifest generation had issues (continuing)" not in src
    assert "TRADEAI_CC_SOURCE_PR=296" not in src
    assert "TRADEAI_CC_DEPLOYED_SHA=" in src
    assert "CIO_SOURCE_PR" in src
    assert "health timeout" in src
    assert "not claiming deploy OK" in src
    assert "Rolling back CURRENT" in src
    assert "write_deploy_receipt" in src
    assert "exit 1" in src
