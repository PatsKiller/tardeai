"""Exact source-set preservation and authority negatives for the three-head rebuild.

Offline: baseline digests are pinned in the review packet, not read from a live host
or fetched Git history. No review authority is granted by these assertions.
"""
from __future__ import annotations

import copy
import builtins
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/stale-n8n-set-20261024"
RECEIPT = json.loads((PACKET / "preservation.json").read_text())
NATIVE = {"holdings-drift-monitor", "options-desk-staleness-monitor", "held-exit-coverage-monitor",
          "cio-ask-research", "jsonl-archive-rotate"}
USER_REVIEWED = (NATIVE - {"jsonl-archive-rotate"}) | {"options-desk-quote-refresh", "schwab-position-sync"}


def _load(path):
    return json.loads((ROOT / path).read_text())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _preserved(doc, spec):
    rows = doc[spec["collection"]]
    keyed = {row[spec["id_key"]]: row for row in rows}
    assert len(rows) == len(keyed), "duplicate source identity"
    assert set(spec["base_object_sha256"]) <= set(keyed), "current-main source row lost"
    assert all(_digest(keyed[key]) == digest for key, digest in spec["base_object_sha256"].items()), "main row changed"
    assert set(spec["added_ids"]) <= set(keyed), "incoming source row lost"
    assert _digest({key: value for key, value in doc.items() if key != spec["collection"]}) == spec["base_top_level_sha256"]


@pytest.mark.parametrize("path", sorted(RECEIPT["collections"]))
def test_all_current_main_objects_and_governance_are_preserved(path):
    _preserved(_load(path), RECEIPT["collections"][path])


@pytest.mark.parametrize("mutation", ["drop-main", "drop-incoming", "change-main", "duplicate", "change-governance"])
def test_preservation_check_rejects_loss_or_silent_authority_drift(mutation):
    path = "config/lane_registry.json"
    spec = RECEIPT["collections"][path]
    doc = copy.deepcopy(_load(path))
    key = next(iter(spec["base_object_sha256"]))
    if mutation == "drop-main":
        doc["lanes"] = [row for row in doc["lanes"] if row["lane_id"] != key]
    elif mutation == "drop-incoming":
        doc["lanes"] = [row for row in doc["lanes"] if row["lane_id"] != "cio-ask-research"]
    elif mutation == "change-main":
        next(row for row in doc["lanes"] if row["lane_id"] == key)["owner"] = "invented-owner"
    elif mutation == "duplicate":
        doc["lanes"].append(copy.deepcopy(doc["lanes"][0]))
    else:
        doc["authority"] = "invented-authority"
    with pytest.raises(AssertionError):
        _preserved(doc, spec)


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


def test_no_spend_registration_or_protected_policy_changed_and_default_governor_refuses():
    from scripts.lib.cio_ask_research import CostGovernor

    for path, digest in RECEIPT["protected_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    called = []

    def must_not_check(*args, **kwargs):
        called.append((args, kwargs))
        raise AssertionError("Unregistered process must refuse before a cost check")

    governor = CostGovernor(check_fn=must_not_check)
    assert governor.admit("deepseek", 0.01) == (False, "PROCESS_NOT_REGISTERED")
    assert called == [] and governor.admitted_usd == 0


@pytest.mark.parametrize("lane", sorted(USER_REVIEWED))
def test_direct_user_review_has_exact_attribution_and_date(lane):
    contract = next(c for c in _load("config/n8n_health_contracts.json")["contracts"] if c["id"] == lane)
    assert contract["status"] == contract["review"]["status"] == "REVIEWED"
    assert contract["review"]["reviewed_by"] == "operator 2026-10-24 ('go', via coordinator)"
    assert contract["review"]["reviewed_on"] == "2026-10-24" and contract["owner"]


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
