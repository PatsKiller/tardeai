"""Fixture-only review of captured registry diffs; no scheduler, DB, network or authority writes.

ANCHOR: REGISTRY_CAPTURE_REVIEW_PACKET_20261024
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from scripts import reconcile_lane_registry as R

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "docs/ops/packets/registry-capture-review-20261024"
SPEC = importlib.util.spec_from_file_location("registry_review_packet", PACKET / "review_packet.py")
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


@pytest.fixture
def host_barrier(monkeypatch):
    calls = []

    def refuse(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("host census, process or network call in offline review")

    for name in ["read_live_crontab", "capture_units_live", "_systemctl_show"]:
        monkeypatch.setattr(R, name, refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield calls
    assert not calls


POST_PACKET_SNAPSHOT_LINES = {1083, 1084, 1085, 1086, 1089, 1090}


def load_base():
    return json.loads(P.read_bundle()[1])


@pytest.mark.parametrize("kind,leaves", [("restriction", 8), ("provenance", 1)])
def test_actual_patches_apply_only_to_owned_tmp_copy_and_exact_metadata(tmp_path, host_barrier, kind, leaves):
    _, original = P.read_bundle()
    fixture = tmp_path / "lane_registry.json"
    fixture.write_bytes(original)
    candidate = P.preview(kind)
    fixture.write_bytes(candidate)
    before, after = json.loads(original), json.loads(fixture.read_bytes())
    P.validate_review_scope(before, after, kind)
    assert len(P.semantic_changes(before, after)) == leaves
    assert [r["lane_id"] for r in before["lanes"]] == [r["lane_id"] for r in after["lanes"]]
    for left, right in zip(before["lanes"], after["lanes"]):
        for field in ["state", "state_since", "scheduler", "dispatch", "watch", "owner", "output_signal"]:
            assert (field in left, left.get(field)) == (field in right, right.get(field))


@pytest.mark.parametrize("lane", sorted(P.LANES))
def test_retired_source_vs_active_captured_cron_remains_a_drift_finding(lane, host_barrier):
    candidate = {r["lane_id"]: r for r in json.loads(P.preview("restriction"))["lanes"]}[lane]
    ledger = json.loads((PACKET / "semantic-fields.json").read_text())
    entry = next(r for r in ledger["lanes"] if r["lane_id"] == lane)
    assert candidate["state"] == "RETIRED" and "dispatch" not in candidate
    assert entry["captured_refs"][0]["captured_line"] in {381, 382}
    assert candidate["stay_on_cron"]["token"] == "alpaca"
    assert entry["disposition"] == "HOLD_AUTHORITY_REVIEW"


@pytest.mark.parametrize("kind,expected", [("restriction", True), ("provenance", False)])
def test_actual_canonical_historical_fixedpoint_contract_is_preserved_or_explicitly_held(host_barrier, kind, expected):
    candidate = json.loads(P.preview(kind))
    snapshot = json.loads((R.DATA_DIR / "scheduler_snapshot_20261009.json").read_text())
    # The packet's registry is frozen at 2026-10-24; lines appended to the snapshot after it (2026-11-01: L1083-L1086,
    # market-risk-evaluate, PR #2409; L1089-L1090, market-quotes-extended) have no row in that registry, so they are not part of this historical contract.
    snapshot["cron_lines"] = [c for c in snapshot["cron_lines"] if c["n"] not in POST_PACKET_SNAPSHOT_LINES]
    result = R.reconcile(candidate, cron_text=R.snapshot_cron_text(snapshot), units=snapshot["units"],
                         f_rows=R.load_rationalization(), evidence=R.load_evidence())
    assert not result["problems"]
    assert (R.dump_registry(candidate) == R.dump_registry(result["registry"])) is expected
    if not expected:
        left = {r["lane_id"]: r for r in candidate["lanes"]}
        right = {r["lane_id"]: r for r in result["registry"]["lanes"]}
        assert [k for k in left if left[k] != right[k]] == ["market-regime-collector"]
        assert left["market-regime-collector"]["rationalization"]["f_id"] == "L213"
        assert right["market-regime-collector"]["rationalization"]["f_id"] == "L199"


def test_rejected_full_diff_accounts_for_every_actual_semantic_leaf(host_barrier):
    manifest, base = P.read_bundle()
    candidate = P.apply_unified_bytes(base, (PACKET / P.PATCH_FILES["mechanical"]).read_text())
    assert hashlib.sha256(candidate).hexdigest() == manifest["cases"]["mechanical"]["candidate_sha256"]
    actual = P.semantic_changes(json.loads(base), json.loads(candidate))
    ledger = json.loads((PACKET / "semantic-fields.json").read_text())
    expected = {
        (r["lane_id"], r["json_pointer"]):
        (r["before"] if r["before_present"] else P.MISSING, r["after"] if r["after_present"] else P.MISSING)
        for r in ledger["changes"]
    }
    assert actual == expected and len(actual) == 177
    assert len({lane for lane, _ in actual}) == 13
    assert all(r["reason"] and r["disposition"] for r in ledger["changes"])
    assert sum(r["leaf_changes"] for r in ledger["lanes"]) == 177
    before = {r["lane_id"] for r in json.loads(base)["lanes"]}
    after = {r["lane_id"] for r in json.loads(candidate)["lanes"]}
    assert before - after == {"prewarm-finviz-strip-map", "prewarm-trade-ai"}
    assert after - before == {"cc-curl-finviz", "cc-curl-accept"}
    with pytest.raises(P.ReviewError, match="rejected"):
        P.preview("mechanical")


@pytest.mark.parametrize("name", ["base-registry-0764.json.gz", "restriction-only.PROPOSED.patch",
                                 "provenance-only.HELD.patch", "mechanical.REJECTED.patch",
                                 "semantic-fields.json", "semantic-fields.csv"])
def test_any_bound_artifact_tamper_refuses_before_preview(tmp_path, host_barrier, name):
    bundle = tmp_path / "packet"
    shutil.copytree(PACKET, bundle)
    path = bundle / name
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(P.ReviewError, match="SHA256"):
        P.preview("restriction", bundle)


@pytest.mark.parametrize("field", ["source_base_registry_sha256", "operator_capture"])
def test_source_or_operator_capture_binding_cannot_be_repointed(tmp_path, host_barrier, field):
    bundle = tmp_path / "packet"
    shutil.copytree(PACKET, bundle)
    path = bundle / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = "0" * 64 if field != "operator_capture" else {"sha256": "0" * 64}
    path.write_text(json.dumps(manifest))
    with pytest.raises(P.ReviewError, match="binding"):
        P.read_bundle(bundle)


@pytest.mark.parametrize("field,value", [("state", "ACTIVE"), ("scheduler", {"kind": "n8n"}),
                                        ("dispatch", {"mode": "live"}), ("owner", "invented"),
                                        ("output_signal", {"kind": "file_mtime", "path": "invented"}),
                                        ("recommendation", "MIGRATE_N8N")])
def test_review_preview_cannot_smuggle_authority_or_unrelated_metadata(field, value, host_barrier):
    before = load_base()
    after = json.loads(P.preview("restriction"))
    row = next(r for r in after["lanes"] if r["lane_id"] == "catalyst-momentum-engine-market")
    row[field] = value
    with pytest.raises(P.ReviewError, match="scope"):
        P.validate_review_scope(before, after, "restriction")


@pytest.mark.parametrize("mutation", ["context", "target", "counts", "overlap"])
def test_unified_parser_refuses_ambiguous_or_mismatching_patch(mutation, host_barrier):
    base = b'{\n  "value": 1\n}\n'
    patch = '--- a/config/lane_registry.json\n+++ b/config/lane_registry.json\n@@ -1,3 +1,3 @@\n {\n-  "value": 1\n+  "value": 2\n }\n'
    assert P.apply_unified_bytes(base, patch) == b'{\n  "value": 2\n}\n'
    if mutation == "context":
        patch = patch.replace('-  "value": 1', '-  "value": 8')
    elif mutation == "target":
        patch = patch.replace('+++ b/config/lane_registry.json', '+++ b/config/other.json')
    elif mutation == "counts":
        patch = patch.replace('@@ -1,3 +1,3 @@', '@@ -1,2 +1,3 @@')
    else:
        patch += patch.split('+++ b/config/lane_registry.json\n')[1]
    with pytest.raises(P.ReviewError):
        P.apply_unified_bytes(base, patch)


def test_units_and_capture_are_not_misrepresented_as_a_new_host_census(host_barrier):
    manifest, _ = P.read_bundle()
    assert manifest["operator_capture"]["sha256"] == P.CAPTURE_SHA256
    assert manifest["operator_capture"]["raw_capture_included"] is False
    assert manifest["operator_capture"]["active_cron_entries"] == 348
    assert "Historical Oct09" in manifest["units_comparator"]["provenance"]
    assert manifest["cases"]["provenance"]["status"].startswith("HELD")
    assert manifest["cases"]["mechanical"]["status"].startswith("REJECTED")
