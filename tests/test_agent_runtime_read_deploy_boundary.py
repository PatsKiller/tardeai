"""The prepared read/monitoring deploy script must keep its safety boundary."""
from __future__ import annotations

import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "agent_runtime" / "deploy_read_monitoring.sh"


def test_deploy_script_is_prepared_and_fail_closed():
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text
    # exact-SHA gate + dirty-tree refusal
    assert 'HEAD_SHA' in text and "!= expected" in text
    assert "refuse to deploy" in text
    # dry-run by default, atomic swap, backup + rollback, health smoke
    assert '--dry-run' in text and 'EXECUTE=0' in text
    assert "mv -T" in text and "rollback" in text and "PREVIOUS_TARGET" in text
    assert "health smoke" in text.lower()


def test_deploy_script_declares_zero_mutation_authority():
    text = SCRIPT.read_text().lower()
    # no database migration and no broker/order/approval/2fa/provider/service/scheduler mutation
    for forbidden in ("psql -f", "migrate", "alembic", "systemctl restart", "crontab", "schwab", "alpaca"):
        assert forbidden not in text, f"deploy script must not perform: {forbidden}"
