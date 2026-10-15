"""F09 n8n onboarding batch 1 (operator N8N Cutover Decision 2026-10-15): broker read / sync lanes.

Lanes: alpaca-live-read-sync, moomoo-live-read-sync, snaptrade-sync, snaptrade-activity-ingest, positions-sync,
alpaca-paper-adapter, portfolio-broker-reconciliation. Every one needs a broker read to plan, so its --dry-run reports
``dry_run_requires_broker_read`` and exits 0 having done nothing.

Proof (hermetic; harness and rules in tests/support/f09_onboarding.py): each dry run with the LIVE cron argv plus
--dry-run in both orders records zero writes, zero broker/DB/sender/network calls and imports no project module but
lib.lane_output; the guard precedes every non-stdlib import; the registry row is staged inert (dispatch off, no
allowlist entry) with a complete activation entry the executor accepts; the effect key is staged (no side claims);
the health contract is REVIEWED with a passing FW-M6 expected_output rule. No DB, no network, no repo write.
"""

from __future__ import annotations

import pytest

from tests.support import f09_onboarding as F

LANES = [
    "alpaca-live-read-sync",
    "moomoo-live-read-sync",
    "snaptrade-sync",
    "snaptrade-activity-ingest",
    "positions-sync",
    "alpaca-paper-adapter",
    "portfolio-broker-reconciliation",
]


@pytest.mark.parametrize("lane", LANES)
def test_dry_run_is_offline_broker_free_and_wins(lane, tmp_path):
    F.check_dry_run(lane, tmp_path)


@pytest.mark.parametrize("lane", LANES)
def test_guard_precedes_every_project_import(lane):
    script = F.staged(lane)["entry_script"]
    if script.endswith(".py"):
        F.assert_py_guard_first(script)
    else:
        F.assert_sh_guard_first(script)


@pytest.mark.parametrize("lane", LANES)
def test_registry_row_is_staged_inert_with_a_complete_activation_entry(lane):
    F.check_staged_registry(lane)


@pytest.mark.parametrize("lane", LANES)
def test_effect_key_is_staged(lane):
    F.check_effect_key(lane)


@pytest.mark.parametrize("lane", LANES)
def test_health_contract_is_reviewed_with_expected_output(lane):
    F.check_contract(lane)


def test_batch_reasons():
    assert {F.staged(lane)["dry_run"]["empty_reason"] for lane in LANES} == {"dry_run_requires_broker_read"}
