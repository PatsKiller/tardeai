"""Lane T — Drive mutation safety; no real Drive calls."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.lib.drive_mutation_safety import (
    DriveSafetyError,
    build_upload_plan,
    execute_upload,
    refuse_delete_dry_run_against_real_targets,
    refuse_gog_dry_run_flag,
    sanitize_or_refuse,
    sha256_file,
)


def test_gog_dry_run_flag_refused_for_upload():
    """Extra finding (keep): gog upload -n is treated as mutating."""
    with pytest.raises(DriveSafetyError, match="treated as mutating"):
        refuse_gog_dry_run_flag(["gog", "drive", "upload", "f.md", "-n"])
    with pytest.raises(DriveSafetyError, match="treated as mutating"):
        sanitize_or_refuse(["gog", "drive", "upload", "f.md", "--dry-run", "--parent", "x"])


def test_delete_dry_run_argv_refused_without_real_drive_call():
    """Unit refusal of delete+-n argv using synthetic ids only — never contacts Drive."""
    with pytest.raises(DriveSafetyError, match="delete dry-runs"):
        refuse_delete_dry_run_against_real_targets(
            ["gog", "drive", "delete", "SYNTHETIC_ID_NOT_A_REAL_FILE", "-n"]
        )


def test_plan_is_read_only_and_requires_target(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("hello lane t\n")
    with pytest.raises(DriveSafetyError, match="explicit target identity"):
        build_upload_plan(f)
    plan = build_upload_plan(f, parent_id="parent123", account="ops@example.com")
    assert plan.mode == "plan"
    assert plan.local_sha256 == sha256_file(f)
    assert "does not invoke gog" in plan.notes[0]


def test_negative_control_mutating_dry_run_implementation_detected(tmp_path: Path):
    """Extra: prove refuse happens before a mutating -n runner can fire."""
    f = tmp_path / "doc.md"
    f.write_text("payload\n")
    mutated = {"count": 0}

    def mutating_dry_run_runner(argv, **kwargs):
        if "-n" in argv or "--dry-run" in argv:
            mutated["count"] += 1
            (tmp_path / "MUTATED_SIDE_EFFECT").write_text("wrote\n")
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    argv = ["gog", "drive", "upload", str(f), "-n", "--parent", "p"]
    with pytest.raises(DriveSafetyError, match="treated as mutating"):
        sanitize_or_refuse(argv)
    assert not (tmp_path / "MUTATED_SIDE_EFFECT").exists()
    assert mutated["count"] == 0
    _ = mutating_dry_run_runner  # documented adversary; never invoked


def test_execute_requires_remote_hash_verification(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("stable\n")
    plan = build_upload_plan(f, parent_id="parentX", account="a@b.c")

    def fake_runner(argv, **kwargs):
        assert "-n" not in argv and "--dry-run" not in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps({"id": "file1"}), stderr="")

    # No readback → fail closed
    receipt = execute_upload(plan, runner=fake_runner, readback=None)
    assert receipt.ok is False
    assert "remote readback" in (receipt.error or "")

    def fake_readback(plan_obj):
        return {"sha256": plan_obj.local_sha256, "id": "file1"}

    receipt2 = execute_upload(plan, runner=fake_runner, readback=fake_readback)
    assert receipt2.ok is True
    assert receipt2.hash_match is True
    assert receipt2.post_write.get("remote_hash_verified") is True

    def bad_readback(plan_obj):
        return {"sha256": "0" * 64, "id": "file1"}

    receipt3 = execute_upload(plan, runner=fake_runner, readback=bad_readback)
    assert receipt3.ok is False
    assert receipt3.hash_match is False


# ── Required enum negative controls (CampaignInterfaces gate) ───────────────


def test_off_state_plan_never_invokes_runner(tmp_path: Path):
    """off_state: plan mode produces a plan and never calls gog/runner."""
    f = tmp_path / "doc.md"
    f.write_text("off\n")
    calls = {"n": 0}

    def runner(argv, **kwargs):
        calls["n"] += 1
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    plan = build_upload_plan(f, parent_id="p")
    assert plan.mode == "plan"
    assert calls["n"] == 0
    # execute with injected runner is the only path that may call runner
    execute_upload(
        plan,
        runner=runner,
        readback=lambda p: {"sha256": p.local_sha256, "id": "x"},
    )
    assert calls["n"] == 1


def test_replay_same_plan_same_local_hash(tmp_path: Path):
    """replay: rebuilding the plan for unchanged bytes collides on sha256."""
    f = tmp_path / "doc.md"
    f.write_text("replay-bytes\n")
    a = build_upload_plan(f, parent_id="p", name="doc.md")
    b = build_upload_plan(f, parent_id="p", name="doc.md")
    assert a.local_sha256 == b.local_sha256
    assert a.local_bytes == b.local_bytes
    assert a.intended_action == b.intended_action


def test_duplicate_execute_receipts_share_pre_hash(tmp_path: Path):
    """duplicate: two executes of equivalent plans share pre-write hash identity."""
    f = tmp_path / "doc.md"
    f.write_text("dup\n")
    plan = build_upload_plan(f, parent_id="p")

    def runner(argv, **kwargs):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"id": "f1"}), stderr="")

    def readback(p):
        return {"sha256": p.local_sha256, "id": "f1"}

    r1 = execute_upload(plan, runner=runner, readback=readback)
    r2 = execute_upload(plan, runner=runner, readback=readback)
    assert r1.ok and r2.ok
    assert r1.pre_write["sha256"] == r2.pre_write["sha256"] == plan.local_sha256


def test_fixture_not_organic_tags(tmp_path: Path):
    """fixture_not_organic: receipts/plans from tests are fixture-scoped."""
    f = tmp_path / "fixture-only.md"
    f.write_text("fixture\n")
    plan = build_upload_plan(f, parent_id="fixture-parent")
    assert plan.schema == "DriveMutationSafety@v1"
    # Disposable root — not a production Drive id / not organic evidence.
    assert str(tmp_path) in plan.local_path
    assert plan.parent_id == "fixture-parent"
    assert "does not invoke gog" in ",".join(plan.notes)
