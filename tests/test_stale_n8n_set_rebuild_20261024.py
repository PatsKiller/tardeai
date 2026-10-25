"""Exact source-set preservation and authority negatives for the three-head rebuild.

Offline: baseline digests are pinned in the review packet, not read from a live host
or fetched Git history. No review authority is granted by these assertions.
"""
from __future__ import annotations

import copy
import builtins
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/stale-n8n-set-20261024"
RECEIPT = json.loads((PACKET / "preservation.json").read_text())
NATIVE = {"holdings-drift-monitor", "options-desk-staleness-monitor", "held-exit-coverage-monitor",
          "cio-ask-research", "jsonl-archive-rotate"}
USER_REVIEWED = (NATIVE - {"jsonl-archive-rotate"}) | {"options-desk-quote-refresh"}


def _load(path):
    return json.loads((ROOT / path).read_text())


def _preserved(spec):
    ids = spec["frozen_ids"]
    keyed = spec["frozen_object_sha256"]
    assert len(ids) == len(set(ids)), "duplicate source identity"
    assert set(ids) == set(keyed), "frozen identity mismatch"
    assert set(spec["base_object_sha256"]) <= set(keyed), "current-main source row lost"
    assert all(keyed[key] == value for key, value in spec["base_object_sha256"].items()), "main row changed"
    assert set(spec["added_ids"]) <= set(keyed), "incoming source row lost"
    assert spec["base_top_level_sha256"] == spec["frozen_top_level_sha256"], "governance changed"


@pytest.mark.parametrize("path", sorted(RECEIPT["collections"]))
def test_frozen_port_preserves_all_accepted_base_objects_and_governance(path):
    # This is the source port proof, not a permanent freeze of unrelated operational rows.
    _preserved(RECEIPT["collections"][path])
    spec = RECEIPT["collections"][path]
    ids = [row[spec["id_key"]] for row in _load(path)[spec["collection"]]]
    assert len(ids) == len(set(ids))
    assert set(spec["added_ids"]) <= set(ids)


@pytest.mark.parametrize("mutation", ["drop-main", "drop-incoming", "change-main", "duplicate", "change-governance"])
def test_preservation_check_rejects_loss_or_silent_authority_drift(mutation):
    spec = copy.deepcopy(RECEIPT["collections"]["config/lane_registry.json"])
    key = next(iter(spec["base_object_sha256"]))
    if mutation in {"drop-main", "drop-incoming"}:
        removed = key if mutation == "drop-main" else "cio-ask-research"
        spec["frozen_object_sha256"].pop(removed)
        spec["frozen_ids"].remove(removed)
    elif mutation == "change-main":
        spec["frozen_object_sha256"][key] = "invented-owner-digest"
    elif mutation == "duplicate":
        spec["frozen_ids"].append(spec["frozen_ids"][0])
    else:
        spec["frozen_top_level_sha256"] = "invented-authority"
    with pytest.raises(AssertionError):
        _preserved(spec)


def test_port_keeps_protected_policy_and_accepted_retention_edits():
    for comparison in RECEIPT["protected_sha256"].values():
        assert comparison["base"] == comparison["source"]
    for comparison in RECEIPT["retention_preservation"].values():
        assert comparison["base_without_fragment_sha256"] == comparison["ported_without_fragment_sha256"]


def test_every_new_admitted_lane_is_shadow_and_live_requests_clamp_to_dry_run():
    from scripts.lib.lane_stage_clamp import clamp_mode

    rows = _load("config/lane_registry.json")["lanes"]
    keyed = {row["lane_id"]: row for row in rows}
    entries = {row["lane_id"]: row for row in _load("config/n8n_run_allowlist.json")["lanes"]}
    for lane in NATIVE:
        row, entry = keyed[lane], entries[lane]
        assert row["scheduler"]["stage"] == "shadow" and row["dispatch"]["mode"] == "dry_run"
        assert row["dispatch"]["tz"] == "America/New_York"
        assert entry["live_arg"] is None and entry["dry_run_arg"] == ["--dry-run"]
        assert clamp_mode(lane, "live", rows)["effective_mode"] == "dry_run"
    assert keyed["options-desk-quote-refresh"]["state"] == "NEVER_SCHEDULED"
    assert keyed["options-desk-quote-refresh"]["scheduler"]["kind"] == "none"
    for lane in ("options-desk-quote-refresh", "schwab-position-sync"):
        assert lane not in entries and "dispatch" not in keyed[lane]
    assert keyed["schwab-position-sync"]["state"] == "ACTIVE"  # main's host-cron decision, no n8n promotion


def test_unregistered_process_fixture_refuses_before_any_cost_check():
    from scripts.lib.cio_ask_research import CostGovernor

    called = []

    def must_not_check(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("Unregistered process must refuse before a cost check")

    governor = CostGovernor(check_fn=must_not_check, registered_fn=lambda _process: False)
    assert governor.admit("deepseek", 0.01) == (False, "PROCESS_NOT_REGISTERED")
    assert called == [] and governor.admitted_usd == 0


@pytest.mark.parametrize("lane", sorted(USER_REVIEWED))
def test_direct_user_review_has_exact_attribution_and_date(lane):
    contract = next(c for c in _load("config/n8n_health_contracts.json")["contracts"] if c["id"] == lane)
    assert contract["status"] == contract["review"]["status"] == "REVIEWED"
    assert contract["review"]["reviewed_by"] == "operator 2026-10-24 ('go', via coordinator)"
    assert contract["review"]["reviewed_on"] == "2026-10-24" and contract["owner"]


def test_archive_review_records_the_explicit_carryforward_directive():
    row = next(c for c in _load("config/n8n_health_contracts.json")["contracts"]
               if c["id"] == "jsonl-archive-rotate")
    assert row["status"] == row["review"]["status"] == "REVIEWED"
    assert row["review"]["reviewed_on"] == "2026-10-24"
    assert "legacy-pr-carryforward.md" in json.dumps(row["review"])


def test_archive_removal_stays_disabled_and_staged_argv_cannot_apply():
    assert _load("config/disk_hygiene_rules.json")["jsonl_retention"]["enabled"] is False
    entry = next(e for e in _load("config/n8n_run_allowlist.json")["lanes"] if e["lane_id"] == "jsonl-archive-rotate")
    assert entry["live_arg"] is None
    assert not any(arg in entry["command"] for arg in ("--apply", "--recover", "APPLY"))
    assert entry["lock"] == "/tmp/tradeai_jsonl_archive_rotate.lock" and entry["timeout_s"] == 1800


@pytest.mark.parametrize("version,status,anchor,allowed", [
    ("20.1.0", "ACTIVE", True, False),
    ("21.0.0", "PROPOSED", True, False),
    ("21.0.0", "ACTIVE", True, True),
    ("22.0.0", "ACTIVE", True, True),
    ("21.0.0", "ACTIVE", False, False),
    ("invalid", "ACTIVE", True, False),
])
def test_research_policy_gate_keeps_version_and_anchor_rules_without_ops_import(
        tmp_path, monkeypatch, version, status, anchor, allowed):
    from scripts.lib import cio_ask_contract as contract

    policy = tmp_path / "policy.md"
    text = f"| {version} | fixture | {status} |\n"
    if anchor:
        text += contract.SIZE_SUGGESTION_POLICY_ANCHOR + "\n"
    policy.write_text(text)
    original_import = builtins.__import__
    forbidden = []

    def isolated_import(name, *args, **kwargs):
        if name.startswith("scripts.lib.ops_controls_core"):
            forbidden.append(name)
            raise AssertionError("Research contract must not import operational services")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", isolated_import)
    assert contract.size_suggestion_allowed(policy) is allowed
    assert contract.size_suggestion_allowed(tmp_path / "missing.md") is False
    assert forbidden == []
