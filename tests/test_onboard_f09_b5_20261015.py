"""F09 n8n onboarding batch 5 (operator N8N Cutover Decision 2026-10-15): options / market-data / ingest lanes.

Lanes: options-iv-snapshot, options-tick, run-options-monitor, active-trader-micro-recorder-premarket,
active-trader-micro-recorder, active-trader-premarket-watch, ingest-tos-watchlists.
options-iv-snapshot, run-options-monitor, active-trader-micro-recorder-premarket, active-trader-micro-recorder,
active-trader-premarket-watch cannot plan without a broker read, so the dry run reports
``dry_run_requires_broker_read`` and exits 0 having done nothing. options-tick, ingest-tos-watchlists plan from
local state; the dry run still reads nothing and reports ``dry_run``.

Proof (hermetic; harness and rules in tests/support/f09_onboarding.py): each dry run with the LIVE cron argv plus
--dry-run in both orders records zero writes, zero broker/DB/sender/network calls and imports no project module but
lib.lane_output (a shell launcher: zero stub calls, no file created); the guard precedes everything else; the registry
row is staged inert (dispatch off, no allowlist entry) with a complete activation entry the executor accepts; the
effect key is staged (no side claims); the health contract is REVIEWED with a passing FW-M6 expected_output rule.
No DB, no network, no repo write.
"""

from __future__ import annotations

import pytest

from tests.support import f09_onboarding as F

LANES = [
    "options-iv-snapshot",
    "options-tick",
    "run-options-monitor",
    "active-trader-micro-recorder-premarket",
    "active-trader-micro-recorder",
    "active-trader-premarket-watch",
    "ingest-tos-watchlists",
]
ORDER_PATHS = []


@pytest.mark.parametrize("lane", LANES)
def test_dry_run_is_offline_broker_free_and_wins(lane, tmp_path):
    F.check_dry_run(lane, tmp_path)


@pytest.mark.parametrize("lane", LANES)
def test_guard_precedes_everything_else(lane):
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


def test_order_paths_are_flagged_and_stay_shadow_only():
    assert sorted(lane for lane in LANES if F.staged(lane)["order_path"]) == ORDER_PATHS
    for lane in ORDER_PATHS:
        assert any(F.ORDER_NOTE.search(n) for n in F.staged(lane)["activation_needs"]), lane
        assert F.staged(lane)["activation_allowlist_entry"]["live_arg"] is None
