#!/usr/bin/env python3
"""Isolated migration rehearsal — every failure path, and the bytes that come back.

The whole point of a guarded migration is what it does when something is wrong.
So this suite builds an isolated replica (byte-copies of the real stores into a
temp producer/served pair), drives the real tool against it, and for every
failure asserts two things: the named rail fired, and the target's bytes are
exactly what they were before.

Nothing here touches the production roots. The replica is a temp directory; the
manifest is rebuilt against it; the tool is the same one an operator would run.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from lib.state_migration import (  # noqa: E402
    MANUAL_CONFLICT,
    build_manifest,
    manifest_hash,
)
from scripts.migrate_state_stores import (  # noqa: E402
    Refusal,
    atomic_write,
    make_backups,
    rail_approval,
    rail_disk,
    rail_expected_sha,
    rail_hashes_unchanged,
    rail_manifest_hash,
    rail_target_path,
    rollback,
    validate_after,
)

TOOL = ROOT / "scripts" / "migrate_state_stores.py"
PROD_ROOT = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/data/portfolios/state")
SERVED_ROOT = Path("/home/johnclaw/trade-ai-releases/persistent-state/data/portfolios/state")

#: A small, fast, representative slice: one clean snapshot-select, one union
#: candidate, one derived cache, one financial conflict.
REHEARSAL_STORES = ["_freshness.json", "snapshot_index.json", "correlation.json", "stops.json"]
ALL_STORES = [
    "_freshness.json",
    "action_signals.json",
    "ai_analysis_cache.json",
    "correlation.json",
    "dividend_calendar.json",
    "finviz_quote_cache.json",
    "health_agent_status.json",
    "lookthrough_themes.json",
    "performance_attribution.json",
    "performance_history.json",
    "portfolio_news.json",
    "retirement_roadmap.json",
    "snapshot_index.json",
    "stops.json",
    "tax_lots.json",
    "technical_snapshot.json",
    "ticker_enrichment_cache.json",
    "trade_journal.json",
]

FAKE_SHA = "a" * 40
APPROVAL = "operator-approval-challenge-response-0001"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _sources_present() -> bool:
    return PROD_ROOT.is_dir() and SERVED_ROOT.is_dir()


needs_sources = pytest.mark.skipif(not _sources_present(), reason="state roots not present on this host")


@pytest.fixture
def replica(tmp_path):
    """A byte-identical isolated copy of both roots. Never the real ones."""
    if not _sources_present():
        pytest.skip("state roots not present")
    p, s = tmp_path / "producer", tmp_path / "served"
    p.mkdir()
    s.mkdir()
    for name in REHEARSAL_STORES:
        for src_root, dst_root in ((PROD_ROOT, p), (SERVED_ROOT, s)):
            src = src_root / name
            if src.is_file():
                shutil.copy2(src, dst_root / name)
    return p, s


@pytest.fixture
def manifest(replica, tmp_path):
    p, s = replica
    doc = build_manifest(REHEARSAL_STORES, p, s)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(doc, indent=1, default=str))
    return doc, path


def _run(args: list[str], out: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [sys.executable, str(TOOL), *args, "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(ROOT),
    )
    return r.returncode, (json.loads(out.read_text()) if out.is_file() else {"_stderr": r.stderr[-800:]})


def _row(doc, store):
    return next(r for r in doc["stores"] if r["store"] == store)


# ── 1. dry run ───────────────────────────────────────────────────────────────


@needs_sources
def test_dry_run_writes_nothing(manifest, replica, tmp_path):
    doc, path = manifest
    _, served = replica
    before = {n: _sha(served / n) for n in REHEARSAL_STORES if (served / n).is_file()}
    rc, receipt = _run(["--manifest", str(path)], tmp_path / "r.json")
    assert rc == 0, receipt
    assert receipt["mode"] == "dry-run"
    after = {n: _sha(served / n) for n in before}
    assert after == before, "a dry run must not change a single byte"
    assert receipt["applied"] == 0


# ── 2/3. successful migration, then idempotent repeat ────────────────────────


@needs_sources
def test_successful_migration_then_idempotent_repeat(manifest, replica, tmp_path):
    doc, path = manifest
    _, served = replica
    target = _row(doc, "_freshness.json")
    args = [
        "--manifest",
        str(path),
        "--apply",
        "--expected-deployed-sha",
        FAKE_SHA,
        "--expected-manifest-sha256",
        manifest_hash(doc),
        "--approval-token",
        APPROVAL,
        "--backup-dir",
        str(tmp_path / "backups"),
        "--only",
        "_freshness.json",
    ]
    env_sha = os.environ.get("DEPLOYED_RELEASE_SHA")
    os.environ["DEPLOYED_RELEASE_SHA"] = FAKE_SHA
    try:
        rc, receipt = _run(args, tmp_path / "r1.json")
        assert rc == 0, receipt
        assert receipt["applied"] == 1, receipt
        first = _sha(served / "_freshness.json")
        assert first == target["planned_content_sha256"], "written bytes must equal the planned bytes"

        # Second run: the manifest's recorded source hashes are now stale for the
        # target, which is exactly what the changed-target rail is for.
        rc2, receipt2 = _run(args, tmp_path / "r2.json")
        assert rc2 != 0
        rails = {r["rail"] for r in receipt2["refusals"]}
        assert "changed_target_hash" in rails, receipt2
        assert _sha(served / "_freshness.json") == first, "a refused repeat must not alter the target"
    finally:
        if env_sha is None:
            os.environ.pop("DEPLOYED_RELEASE_SHA", None)
        else:
            os.environ["DEPLOYED_RELEASE_SHA"] = env_sha


# ── 4/5. changed source / target hash ────────────────────────────────────────


@needs_sources
def test_changed_source_hash_is_refused(manifest, replica):
    doc, _ = manifest
    producer, _ = replica
    row = _row(doc, "_freshness.json")
    (producer / "_freshness.json").write_text('{"tampered": true}')
    with pytest.raises(Refusal) as exc:
        rail_hashes_unchanged(row)
    assert exc.value.rail == "changed_source_hash"


@needs_sources
def test_changed_target_hash_is_refused(manifest, replica):
    doc, _ = manifest
    _, served = replica
    row = _row(doc, "_freshness.json")
    (served / "_freshness.json").write_text('{"tampered": true}')
    with pytest.raises(Refusal) as exc:
        rail_hashes_unchanged(row)
    assert exc.value.rail == "changed_target_hash"


# ── 6/7. missing and corrupted backup ────────────────────────────────────────


@needs_sources
def test_missing_backup_is_refused(manifest, tmp_path):
    doc, _ = manifest
    row = dict(_row(doc, "_freshness.json"))
    row["producer_path"] = str(tmp_path / "nope.json")
    row["served_path"] = str(tmp_path / "also-nope.json")
    with pytest.raises(Refusal) as exc:
        make_backups(row, tmp_path / "b", "stamp")
    assert exc.value.rail == "unverified_backup"


@needs_sources
def test_corrupted_backup_is_detected(manifest, tmp_path, monkeypatch):
    doc, _ = manifest
    row = _row(doc, "_freshness.json")
    real_copy = shutil.copy2

    def corrupt(src, dst, *a, **k):
        real_copy(src, dst, *a, **k)
        Path(dst).write_text("{corrupted")
        return dst

    monkeypatch.setattr(shutil, "copy2", corrupt)
    with pytest.raises(Refusal) as exc:
        make_backups(row, tmp_path / "b2", "stamp")
    assert exc.value.rail == "unverified_backup"


# ── 8. insufficient disk ─────────────────────────────────────────────────────


@needs_sources
def test_insufficient_disk_is_refused(manifest, replica):
    doc, _ = manifest
    _, served = replica
    with pytest.raises(Refusal) as exc:
        rail_disk(served / "_freshness.json", 10**15)
    assert exc.value.rail == "insufficient_disk"


# ── 9. active writer ─────────────────────────────────────────────────────────


@needs_sources
def test_active_writer_is_refused(manifest, monkeypatch):
    from scripts import migrate_state_stores as mod

    doc, _ = manifest
    row = dict(_row(doc, "_freshness.json"))
    row["producer_schedule"] = ["systemd: pretend-writer.service"]

    class R:
        stdout = "active"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: R())
    with pytest.raises(Refusal) as exc:
        mod.rail_producers_quiesced(row, check=True)
    assert exc.value.rail == "running_affected_writer"
    # and with the check off it reports rather than raises
    assert mod.rail_producers_quiesced(row, check=False)["running"]


# ── 10/11. wrong deployed SHA / manifest hash ────────────────────────────────


def test_wrong_deployed_sha_is_refused():
    with pytest.raises(Refusal) as exc:
        rail_expected_sha("b" * 40, "c" * 40)
    assert exc.value.rail == "unexpected_deployed_sha"
    with pytest.raises(Refusal) as exc:
        rail_expected_sha(None, "c" * 40)
    assert exc.value.rail == "missing_expected_deployed_sha"


@needs_sources
def test_wrong_manifest_hash_is_refused(manifest):
    doc, _ = manifest
    with pytest.raises(Refusal) as exc:
        rail_manifest_hash(doc, "d" * 64)
    assert exc.value.rail == "unexpected_manifest"
    assert rail_manifest_hash(doc, manifest_hash(doc)) == manifest_hash(doc)


@needs_sources
def test_a_tampered_manifest_fails_its_own_recorded_hash(manifest):
    doc, _ = manifest
    tampered = json.loads(json.dumps(doc, default=str))
    tampered["stores"][0]["strategy"] = "AUTHORITATIVE_REPLACE"
    with pytest.raises(Refusal) as exc:
        rail_manifest_hash(tampered, tampered["manifest_sha256"])
    assert exc.value.rail == "unexpected_manifest"


# ── 12. invalid schema / failed post-write validation ────────────────────────


@needs_sources
def test_invalid_schema_after_write_is_caught(manifest, replica):
    doc, _ = manifest
    _, served = replica
    row = _row(doc, "_freshness.json")
    target = served / "_freshness.json"
    target.write_text("{not json")
    with pytest.raises(Refusal) as exc:
        validate_after(row, target, None)
    assert exc.value.rail == "failed_post_write_validation"


@needs_sources
def test_hash_mismatch_after_write_is_caught(manifest, replica):
    doc, _ = manifest
    _, served = replica
    row = _row(doc, "_freshness.json")
    with pytest.raises(Refusal) as exc:
        validate_after(row, served / "_freshness.json", "e" * 64)
    assert exc.value.rail == "failed_post_write_validation"


# ── 13/14. partial write and interruption ────────────────────────────────────


@needs_sources
def test_an_interrupted_write_leaves_the_target_untouched(replica, monkeypatch):
    _, served = replica
    target = served / "_freshness.json"
    before_bytes, before_sha = target.read_bytes(), _sha(target)

    real_replace = os.replace

    def boom(src, dst):
        raise KeyboardInterrupt("simulated interruption mid-write")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(KeyboardInterrupt):
        atomic_write(target, {"new": "content"}, target)
    monkeypatch.setattr(os, "replace", real_replace)

    assert target.read_bytes() == before_bytes, "an interrupted write must not be partially visible"
    assert _sha(target) == before_sha
    leftovers = list(served.glob(".*tmp"))
    assert leftovers == [], f"temp files must be cleaned up: {leftovers}"


# ── 15. conflicting authoritative records ────────────────────────────────────


@needs_sources
def test_financial_conflict_is_never_applied(manifest, replica, tmp_path):
    doc, path = manifest
    _, served = replica
    row = _row(doc, "stops.json")
    assert row["strategy"] == MANUAL_CONFLICT
    assert row["financial_truth_store"] is True
    assert "FAIL CLOSED" in row["strategy_reason"]

    before = _sha(served / "stops.json")
    os.environ["DEPLOYED_RELEASE_SHA"] = FAKE_SHA
    try:
        rc, receipt = _run(
            [
                "--manifest",
                str(path),
                "--apply",
                "--expected-deployed-sha",
                FAKE_SHA,
                "--expected-manifest-sha256",
                manifest_hash(doc),
                "--approval-token",
                APPROVAL,
                "--backup-dir",
                str(tmp_path / "b3"),
                "--only",
                "stops.json",
            ],
            tmp_path / "r3.json",
        )
    finally:
        os.environ.pop("DEPLOYED_RELEASE_SHA", None)
    entry = receipt["stores"][0]
    assert entry["skipped"] is True
    assert "MANUAL_CONFLICT" in entry["reason"]
    assert _sha(served / "stops.json") == before, "a fail-closed store must not be written"


# ── 16. automatic rollback restores the exact bytes ──────────────────────────


@needs_sources
def test_rollback_restores_byte_identical_content(manifest, replica, tmp_path):
    doc, _ = manifest
    _, served = replica
    row = _row(doc, "_freshness.json")
    target = served / "_freshness.json"
    before_bytes, before_sha = target.read_bytes(), _sha(target)

    backups = make_backups(row, tmp_path / "b4", "stamp")
    target.write_text('{"corrupted": true}')
    assert _sha(target) != before_sha

    result = rollback(row, backups, target)
    assert result["rolled_back"] is True
    assert result["bytes_identical"] is True
    assert target.read_bytes() == before_bytes
    assert _sha(target) == before_sha


# ── 17. approval ─────────────────────────────────────────────────────────────


def test_apply_without_operator_approval_is_refused():
    with pytest.raises(Refusal) as exc:
        rail_approval(None, None)
    assert exc.value.rail == "missing_operator_approval"
    with pytest.raises(Refusal) as exc:
        rail_approval("short", None)
    assert exc.value.rail == "missing_operator_approval"
    with pytest.raises(Refusal) as exc:
        rail_approval(APPROVAL, "a-different-challenge-entirely-0002")
    assert exc.value.rail == "missing_operator_approval"
    rail_approval(APPROVAL, APPROVAL)  # matching challenge is accepted


# ── 18. forbidden targets ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "target,rail",
    [
        ("/", "forbidden_target"),
        (str(Path.home()), "forbidden_target"),
        (str(ROOT), "forbidden_target"),
        ("relative/path.json", "unresolved_path"),
        ("/etc/passwd", "forbidden_target"),
        ("/etc/state-of-the-nation.json", "forbidden_target"),
    ],
)
def test_forbidden_targets_are_refused(target, rail):
    with pytest.raises(Refusal) as exc:
        rail_target_path(Path(target), governed_root="/home/johnclaw/trade-ai-releases/persistent-state")
    assert exc.value.rail == rail


def test_a_target_outside_the_governed_root_is_refused(tmp_path):
    """Containment is against the manifest's declared root, not a substring."""
    inside = tmp_path / "served" / "x.json"
    inside.parent.mkdir()
    inside.write_text("{}")
    rail_target_path(inside, governed_root=tmp_path / "served")  # accepted
    with pytest.raises(Refusal) as exc:
        rail_target_path(inside, governed_root=tmp_path / "elsewhere")
    assert exc.value.rail == "forbidden_target"


def test_a_missing_governed_root_is_refused(tmp_path):
    f = tmp_path / "x.json"
    f.write_text("{}")
    with pytest.raises(Refusal) as exc:
        rail_target_path(f, governed_root=None)
    assert exc.value.rail == "unresolved_path"


@needs_sources
def test_a_directory_target_is_refused(tmp_path):
    d = tmp_path / "state"
    d.mkdir()
    with pytest.raises(Refusal) as exc:
        rail_target_path(d, governed_root=tmp_path)
    assert exc.value.rail == "broad_recursive_target"


# ── the tool refuses apply without any of its rails ──────────────────────────


@needs_sources
@pytest.mark.parametrize(
    "drop,rail",
    [
        ("--expected-deployed-sha", "missing_expected_deployed_sha"),
        ("--expected-manifest-sha256", "missing_expected_manifest_sha256"),
        ("--approval-token", "missing_operator_approval"),
        ("--backup-dir", "unverified_backup"),
    ],
)
def test_apply_refuses_when_a_rail_is_missing(manifest, tmp_path, drop, rail):
    doc, path = manifest
    full = {
        "--expected-deployed-sha": FAKE_SHA,
        "--expected-manifest-sha256": manifest_hash(doc),
        "--approval-token": APPROVAL,
        "--backup-dir": str(tmp_path / "b5"),
    }
    full.pop(drop)
    args = ["--manifest", str(path), "--apply"]
    for k, v in full.items():
        args += [k, v]
    os.environ["DEPLOYED_RELEASE_SHA"] = FAKE_SHA
    try:
        rc, receipt = _run(args, tmp_path / f"r_{rail}.json")
    finally:
        os.environ.pop("DEPLOYED_RELEASE_SHA", None)
    assert rc == 2, receipt
    assert receipt["refusals"][0]["rail"] == rail, receipt


# ── the manifest covers every named store ────────────────────────────────────


@needs_sources
def test_every_named_store_has_a_manifest_row():
    doc = json.loads((ROOT / "evidence" / "whole_site" / "MIGRATION_MANIFEST.json").read_text())
    assert {r["store"] for r in doc["stores"]} == set(ALL_STORES)
    assert doc["store_count"] == 18
    for r in doc["stores"]:
        for field in (
            "producer_path",
            "served_path",
            "canonical_target",
            "kind",
            "strategy",
            "strategy_reason",
            "rollback_strategy",
            "validation_check",
            "producers",
            "consumers",
            "producer_schedule",
        ):
            assert r.get(field) is not None, f"{r['store']} missing {field}"
        assert r["strategy"] in (
            "IDENTICAL_BIND",
            "AUTHORITATIVE_REPLACE",
            "APPEND_ONLY_UNION",
            "VERSIONED_SNAPSHOT_SELECT",
            "REBUILD_DERIVED",
            "MANUAL_CONFLICT",
            "RETIRE_DUPLICATE",
        )


@needs_sources
def test_every_financial_store_fails_closed():
    doc = json.loads((ROOT / "evidence" / "whole_site" / "MIGRATION_MANIFEST.json").read_text())
    fin = [r for r in doc["stores"] if r["financial_truth_store"]]
    assert len(fin) == 5
    for r in fin:
        assert r["strategy"] == MANUAL_CONFLICT, f"{r['store']} must fail closed"
        assert r["requires_operator"] is True
        assert "FAIL CLOSED" in r["strategy_reason"]
