"""G0 — canonical acceptance evaluator must be remote main (or attested parent).

Mandatory: remote main evaluator = old G2; local feature branch = fixed G2
=> G0 FAIL => CORE_CIO_PRODUCTION_ACCEPTANCE FAIL.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.cio_acceptance_v4 import (  # noqa: E402
    eval_g0_canonical_acceptance_evaluator,
    evaluate_live_snapshot,
)
from scripts.lib.cio_remote_sha_truth import (  # noqa: E402
    ACCEPTANCE_EVALUATOR_RELPATH,
    ACCEPTANCE_RUNNER_RELPATH,
    CLASS_ATTESTATION,
    CLASS_RUNTIME,
    collect_evaluator_attestation,
)
from test_cio_acceptance_v4 import _clean_snap, _pass_g0_attestation  # noqa: E402

OLD_G2 = (
    "def eval_g2_release_manifest_parity():\n"
    "    # OLD G2: requires live_eq_main even for pin-only parent\n"
    "    pin_ok = live_eq_main and pin_only_parent\n"
)
FIXED_G2 = (
    "def eval_g2_release_manifest_parity():\n"
    "    # FIXED G2: live may equal attested content SHA when pin_only_parent\n"
    "    pin_ok = pin_only_parent and (canonical_eq_live or backend_eq_live)\n"
    "    pin_ok = pin_ok and (live_eq_main or canonical_eq_live)\n"
)
OLD_RUNNER = "print('old runner')\n"
NEW_RUNNER = "print('same runner body as main')\n"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "g0@test.local")
    _git(repo, "config", "user.name", "G0 Tester")
    return repo


def _write_acceptance(repo: Path, evaluator: str, runner: str) -> None:
    ev = repo / ACCEPTANCE_EVALUATOR_RELPATH
    rn = repo / ACCEPTANCE_RUNNER_RELPATH
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(evaluator, encoding="utf-8")
    rn.write_text(runner, encoding="utf-8")


def _sha(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).stdout.strip()


def test_g0_required_attestation_fields_from_collect(tmp_path):
    repo = _init_repo(tmp_path)
    _write_acceptance(repo, OLD_G2, OLD_RUNNER)
    _git(repo, "add", ACCEPTANCE_EVALUATOR_RELPATH, ACCEPTANCE_RUNNER_RELPATH)
    _git(repo, "commit", "-m", "old g2")
    main = _sha(repo)
    truth = {
        "proven": True,
        "remote_main_sha": main,
        "main_commit_class": CLASS_RUNTIME,
        "attested_runtime_content_sha": main,
    }
    att = collect_evaluator_attestation(repo, remote_truth=truth)
    required = (
        "acceptance_evaluator_commit_sha",
        "git_branch",
        "worktree_clean",
        "untracked_count",
        "evaluator_file_sha256",
        "runner_file_sha256",
        "remote_main_sha",
        "main_commit_class",
        "attested_runtime_content_sha",
        "evaluator_diff_vs_remote_main",
    )
    for k in required:
        assert k in att, k
    assert att["worktree_clean"] is True
    assert att["untracked_count"] == 0
    assert att["evaluator_diff_vs_remote_main"] == []
    assert att["acceptance_evaluator_commit_sha"] == main
    g = eval_g0_canonical_acceptance_evaluator(attestation=att)
    assert g["status"] == "PASS"


def test_unmerged_g2_fix_fails_g0_and_core(tmp_path):
    """remote main = old G2; local feature branch = fixed G2 => G0+CORE FAIL."""
    repo = _init_repo(tmp_path)
    _write_acceptance(repo, OLD_G2, OLD_RUNNER)
    _git(repo, "add", ACCEPTANCE_EVALUATOR_RELPATH, ACCEPTANCE_RUNNER_RELPATH)
    _git(repo, "commit", "-m", "old g2 on main")
    main = _sha(repo)

    _git(repo, "checkout", "-b", "fix/g2-pin")
    _write_acceptance(repo, FIXED_G2, OLD_RUNNER)
    _git(repo, "add", ACCEPTANCE_EVALUATOR_RELPATH)
    _git(repo, "commit", "-m", "feature-branch-only G2 fix")

    truth = {
        "proven": True,
        "remote_main_sha": main,
        "main_commit_class": CLASS_RUNTIME,
        "attested_runtime_content_sha": main,
        "local_matches_remote": True,
    }
    att = collect_evaluator_attestation(repo, remote_truth=truth)
    assert att["acceptance_evaluator_commit_sha"] != main
    assert ACCEPTANCE_EVALUATOR_RELPATH in att["evaluator_diff_vs_remote_main"]
    assert att["evaluator_files_match_remote_main"] is False

    g0 = eval_g0_canonical_acceptance_evaluator(attestation=att)
    assert g0["status"] == "FAIL"
    assert "unmerged" in g0["reason"].lower() or "differ" in g0["reason"].lower()

    snap = _clean_snap()
    snap["evaluator_attestation"] = att
    v = evaluate_live_snapshot(snap)
    by = {g["gate"]: g for g in v["gates"]}
    assert by["G0_CANONICAL_ACCEPTANCE_EVALUATOR"]["status"] == "FAIL"
    assert v["CORE_CIO_PRODUCTION_ACCEPTANCE"] == "FAIL"
    assert v["PRODUCTION_ACCEPTANCE"] == "FAIL"
    assert v["FULL_INVESTMENT_OFFICE_ACCEPTANCE"] != "PASS"


def test_g0_dirty_evaluator_fails(tmp_path):
    repo = _init_repo(tmp_path)
    _write_acceptance(repo, OLD_G2, OLD_RUNNER)
    _git(repo, "add", ACCEPTANCE_EVALUATOR_RELPATH, ACCEPTANCE_RUNNER_RELPATH)
    _git(repo, "commit", "-m", "old g2")
    main = _sha(repo)
    (repo / ACCEPTANCE_EVALUATOR_RELPATH).write_text(FIXED_G2, encoding="utf-8")
    truth = {
        "proven": True,
        "remote_main_sha": main,
        "main_commit_class": CLASS_RUNTIME,
        "attested_runtime_content_sha": main,
    }
    att = collect_evaluator_attestation(repo, remote_truth=truth)
    assert att["worktree_clean"] is False
    assert att["evaluator_files_dirty"] is True
    g = eval_g0_canonical_acceptance_evaluator(attestation=att)
    assert g["status"] == "FAIL"
    assert "dirty" in g["reason"]


def test_g0_attestation_only_matching_content_parent_passes(tmp_path):
    repo = _init_repo(tmp_path)
    _write_acceptance(repo, OLD_G2, OLD_RUNNER)
    man = repo / "docs/investment-office/RELEASE_MANIFEST.json"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text('{"status":"production"}\n', encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "content parent")
    content = _sha(repo)

    man.write_text('{"status":"production","canonical_source_sha":"%s"}\n' % content)
    _git(repo, "add", "docs/investment-office/RELEASE_MANIFEST.json")
    _git(repo, "commit", "-m", "attestation pin")
    pin = _sha(repo)

    # Check out the content parent (HEAD != remote pin) with identical evaluator files.
    _git(repo, "checkout", content)
    truth = {
        "proven": True,
        "remote_main_sha": pin,
        "main_commit_class": CLASS_ATTESTATION,
        "attested_runtime_content_sha": content,
    }
    att = collect_evaluator_attestation(repo, remote_truth=truth)
    assert att["acceptance_evaluator_commit_sha"] == content
    assert att["evaluator_diff_vs_remote_main"] == []
    assert att["evaluator_files_match_attested_content"] is True
    g = eval_g0_canonical_acceptance_evaluator(attestation=att)
    assert g["status"] == "PASS"


def test_g0_feature_branch_same_files_but_not_main_fails():
    """HEAD != remote main and not attestation-only parent → FAIL even if blobs match."""
    sha_main = "b" * 40
    att = _pass_g0_attestation(sha_main)
    att["acceptance_evaluator_commit_sha"] = "f" * 40
    att["git_branch"] = "fix/cio-g2-attestation-pin"
    att["evaluator_diff_vs_remote_main"] = []
    att["evaluator_files_match_remote_main"] = True
    g = eval_g0_canonical_acceptance_evaluator(attestation=att)
    assert g["status"] == "FAIL"
    v = evaluate_live_snapshot(_clean_snap(evaluator_attestation=att))
    assert v["CORE_CIO_PRODUCTION_ACCEPTANCE"] == "FAIL"
