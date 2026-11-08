"""LQ-20261107-716: jsonl-archive-rotate leaves SHADOW and joins the relay live set.

Fail-before / pass-after. On the pre-promotion registry (``scheduler.stage: shadow``,
``dispatch.mode: dry_run``, allowlist ``live_arg: null``) the first assertion of every test below fails:
``registry_live_lanes`` returns a list without the lane and the render reports nothing at all (the
``dispatch.mode != live`` short-circuit at ``n8n_relay_live_lanes.registry_live_lanes`` runs before the
stage is looked at, so the lane was absent from the render with an EMPTY ``excluded`` map — the silent
FAIL_CONFIG symptom that produced this task).

What the promotion is, and what it is not: the lane stays a filesystem lane that ARCHIVES and never
deletes an archive segment (AGENTS.md §24.12, §23.14); the live argv is the same ``--apply --confirm
APPLY`` the operator approved on 2026-10-23, now reachable from the dispatcher instead of only by hand.
Arming is still gated: on this host ``--apply`` refuses every store ``fd_visibility_unknown`` until the
root-owned ``/usr/local/sbin/tradeai-fd-holders`` helper is installed (LQ-20261107-501 route 1). That is
why the promotion ships STAGED in the effect-key sense (``n8n_claim: false``) — the executor's
behaviour is unchanged by the key; see ``test_effect_key_is_staged_and_inert``.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.lib import lane_dispatch as LD
from scripts.lib import lane_stage_clamp as SC
from scripts.lib import n8n_relay_live_lanes as RLL
from scripts.lib.effect_claim import load_effect_config, load_effect_lanes
from scripts.lib.n8n_health_contracts import registry_targets

ROOT = Path(__file__).resolve().parents[1]
LANE = "jsonl-archive-rotate"
LIVE_ARG = ["--apply", "--confirm", "APPLY"]
PROMOTED_STAGE = "canary"  # LIVE_STAGES = {canary, cutover}; canary is the first live rung


def _registry() -> dict:
    return json.loads((ROOT / RLL.REGISTRY_REL).read_text(encoding="utf-8"))


def _allowlist() -> dict:
    return json.loads((ROOT / RLL.ALLOWLIST_REL).read_text(encoding="utf-8"))


def _contracts() -> dict:
    return json.loads((ROOT / "config/n8n_health_contracts.json").read_text(encoding="utf-8"))


def _row() -> dict:
    for row in _registry()["lanes"]:
        if row.get("lane_id") == LANE:
            return row
    raise AssertionError(f"{LANE} has no row in {RLL.REGISTRY_REL}")


def _entry() -> dict:
    for entry in _allowlist()["lanes"]:
        if entry.get("lane_id") == LANE:
            return entry
    raise AssertionError(f"{LANE} has no entry in {RLL.ALLOWLIST_REL}")


def _contract() -> dict:
    for contract in _contracts()["contracts"]:
        if contract.get("id") == LANE and contract.get("kind") == "lane":
            return contract
    raise AssertionError(f"{LANE} has no kind=lane contract in config/n8n_health_contracts.json")


def test_registry_row_declares_a_live_stage_and_live_dispatch_block():
    row = _row()
    sched = row["scheduler"]
    assert sched["stage"] == PROMOTED_STAGE, "a shadow stage is never on the relay live list"
    assert sched["kind"] == "n8n" and sched["expression"] == "dispatcher"
    assert row["dispatch"]["mode"] == "live"
    assert row["dispatch"]["class"] == "hygiene"
    # hygiene is permitted under transient-2 (config/n8n_retry_policies.json permitted_classes).
    assert row["dispatch"]["retry_policy"] == "transient-2"
    assert row["state"] == "ACTIVE"


def test_allowlist_entry_carries_the_approved_live_argv_and_keeps_the_dry_run():
    entry = _entry()
    assert entry["live_arg"] == LIVE_ARG
    assert entry["dry_run_arg"] == ["--dry-run"]
    # The output verdict is enforced in live mode because the lane writes produced_count (LaneRunReceipt@v2).
    assert entry["output_receipt"] == "v2"
    assert entry["output_signal"] == _row()["output_signal"]["path"]


def test_lane_is_on_the_computed_relay_live_set_with_no_exclusion_entry():
    lanes, excluded = RLL.registry_live_lanes(_registry(), _allowlist())
    assert LANE in lanes
    assert LANE not in excluded


def test_dispatch_gates_admit_the_row():
    ok, why = LD.dispatch_eligible(_row())
    assert ok, why
    admitted, why = LD.r1_class_admission(_row(), _entry())
    assert admitted, why


def test_stage_clamp_lets_a_live_request_through():
    clamp = SC.clamp_mode(LANE, "live", _registry()["lanes"])
    assert clamp["clamped"] is False, clamp
    assert clamp["effective_mode"] == "live"
    assert clamp["stage"] == PROMOTED_STAGE


def test_health_contract_moves_with_the_registry_row():
    contract = _contract()
    assert contract["status"] == "REVIEWED"  # LIVE_LIST_CONTRACT_NOT_LIVE otherwise
    assert contract["stage"] == PROMOTED_STAGE  # STAGE_DRIFT / CONTRACT_STAGE_MISMATCH otherwise
    assert contract["target_reason"] == registry_targets(_registry())[LANE] == f"stage:{PROMOTED_STAGE}"
    assert contract["expected_output"]["rule"] == "empty_allowed"
    assert contract["expected_output"]["produced_field"] == "produced_count"


def test_effect_key_is_staged_and_inert():
    spec = _allowlist_effect_spec()
    assert spec["process"] == LANE and spec["input_version"] == "v1"
    assert spec["effects"] == ["filesystem"]
    assert spec["slot"] == "scheduled_minute" and spec["schedule"] == "45 16 * * 1-5"
    assert spec["slot_tz"] == "America/New_York"
    # STAGED: the executor claims nothing, so the live path behaves exactly as it did before the key existed.
    assert spec["n8n_claim"] is False and spec["cron_claim"] is False
    assert LANE not in load_effect_config(), "a staged key must not arm the executor"
    assert LANE in load_effect_lanes()


def _allowlist_effect_spec() -> dict:
    doc = json.loads((ROOT / "config/n8n_effect_keys.json").read_text(encoding="utf-8"))
    spec = doc["lanes"].get(LANE)
    assert spec is not None, f"{LANE} is relay-live and must be keyed in config/n8n_effect_keys.json"
    return spec


def test_negative_control_a_shadow_row_is_still_refused():
    """The predicate the tests above rely on discriminates: the PRE-promotion row is not live, and says why."""
    row = copy.deepcopy(_row())
    row["scheduler"]["stage"] = "shadow"
    row["dispatch"]["mode"] = "dry_run"
    registry = {"lanes": [row]}
    allowlist = {"lanes": [dict(_entry(), live_arg=None)]}
    lanes, excluded = RLL.registry_live_lanes(registry, allowlist)
    assert LANE not in lanes
    # The dry_run short-circuit happens before the stage is read, so the lane is silently absent — the
    # exact audit gap this promotion closes; the stage branch is the one that names a shadow row.
    assert LANE not in excluded
    assert SC.clamp_mode(LANE, "live", [row])["clamped"] is True


@pytest.mark.parametrize("lane", [LANE])
def test_the_lane_is_on_the_live_set_once_only(lane):
    lanes, _ = RLL.registry_live_lanes(_registry(), _allowlist())
    assert lanes.count(lane) == 1
