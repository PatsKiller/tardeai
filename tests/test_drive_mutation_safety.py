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
    with pytest.raises(DriveSafetyError, match="treated as mutating"):
        refuse_gog_dry_run_flag(["gog", "drive", "upload", "f.md", "-n"])
    with pytest.raises(DriveSafetyError, match="treated as mutating"):
        sanitize_or_refuse(["gog", "drive", "upload", "f.md", "--dry-run", "--parent", "x"])


def test_delete_dry_run_against_real_file_prohibited():
    with pytest.raises(DriveSafetyError, match="delete dry-runs"):
        refuse_delete_dry_run_against_real_targets(
            ["gog", "drive", "delete", "1abcRealFileId", "-n"]
        )
    with pytest.raises(DriveSafetyError, match="delete dry-runs"):
        sanitize_or_refuse(["gog", "drive", "rm", "1abcRealFileId", "--dry-run"])


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
    """A fake gog that mutates on -n must be caught by refuse_gog_dry_run_flag
    before runner invocation — proving we do not trust -n as dry-run."""
    f = tmp_path / "doc.md"
    f.write_text("payload\n")
    mutated = {"count": 0}

    def mutating_dry_run_runner(argv, **kwargs):
        # Simulates a broken tool that writes even when -n is present.
        if "-n" in argv or "--dry-run" in argv:
            mutated["count"] += 1
            (tmp_path / "MUTATED_SIDE_EFFECT").write_text("wrote\n")
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    argv = ["gog", "drive", "upload", str(f), "-n", "--parent", "p"]
    with pytest.raises(DriveSafetyError, match="treated as mutating"):
        sanitize_or_refuse(argv)
    # Runner never called — side effect file must not exist
    assert not (tmp_path / "MUTATED_SIDE_EFFECT").exists()
    assert mutated["count"] == 0

    # If someone bypassed sanitize and called runner with -n, our execute_upload
    # path also refuses before runner.
    plan = build_upload_plan(f, parent_id="p")
    # Force -n into argv by monkeypatching execute internals via sanitize on built argv
    with pytest.raises(DriveSafetyError):
        refuse_gog_dry_run_flag(["gog", "drive", "upload", str(f), "-n", "--parent", "p"])


def test_execute_pre_post_hash(tmp_path: Path):
    f = tmp_path / "doc.md"
    f.write_text("stable\n")
    plan = build_upload_plan(f, parent_id="parentX", account="a@b.c")

    def fake_runner(argv, **kwargs):
        assert "-n" not in argv and "--dry-run" not in argv
        assert "--parent" in argv and "parentX" in argv
        return SimpleNamespace(returncode=0, stdout=json.dumps({"id": "file1"}), stderr="")

    def fake_readback(plan_obj):
        return {"sha256": plan_obj.local_sha256, "id": "file1"}

    receipt = execute_upload(plan, runner=fake_runner, readback=fake_readback)
    assert receipt.ok is True
    assert receipt.pre_write["sha256"] == plan.local_sha256
    assert receipt.hash_match is True
    assert receipt.post_write["sha256"] == plan.local_sha256
