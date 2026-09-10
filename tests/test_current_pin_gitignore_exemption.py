"""The pin gate must exempt git-ignored runtime files -- and nothing else.

2026-09-10: a promote was refused with `unpinned_extra:66` while `diff_count`
was 0. Every tracked file in the candidate release was byte-identical to
SOURCE_COMMIT. The 66 were cron-written generated docs
(`docs/project/STATE_OF_REPO_LATEST.md`, `docs/governance/*_latest.*`,
`docs/hermes/**`, `docs/maturity_hardening/*_latest.*`) that land in the dev
tree and get rsynced into the release by `overlay_main`.

The module docstring already said "Runtime / generated -- never part of the
pin". SKIP_PARTS just didn't know these names, and a hand-kept list never will.

These controls pin BOTH halves: ignored files are exempt, and everything else
still fails the gate. A gate that cannot go red proves nothing.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.lib.current_pin_integrity import _ignored_by_git, evaluate_pin


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / "docs" / "governance").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    (r / ".gitignore").write_text(
        "docs/governance/*_latest.json\ndocs/project/STATE_OF_REPO_LATEST.md\n",
        encoding="utf-8",
    )
    return r


# --- the exemption ------------------------------------------------------------

def test_gitignored_runtime_docs_are_exempt(repo: Path):
    """The exact class that blocked the 2026-09-10 promote."""
    got = _ignored_by_git(repo, ["docs/governance/governance_status_latest.json"])
    assert "docs/governance/governance_status_latest.json" in got


def test_a_path_git_does_not_ignore_is_never_exempt(repo: Path):
    """The gate must still catch a genuine stray file."""
    got = _ignored_by_git(repo, ["docs/governance/smuggled_in.md"])
    assert got == set()


def test_mixed_batch_separates_correctly(repo: Path):
    got = _ignored_by_git(
        repo,
        ["docs/governance/governance_status_latest.json", "docs/governance/smuggled_in.md"],
    )
    assert got == {"docs/governance/governance_status_latest.json"}


# --- failure modes that must NOT silently exempt everything -------------------

def test_empty_input_calls_nothing_and_returns_empty(repo: Path):
    assert _ignored_by_git(repo, []) == set()


def test_a_broken_repo_exempts_NOTHING(tmp_path: Path):
    """Fail closed. A git that cannot answer must not wave everything through.

    The dangerous bug would be treating a git error as 'all ignored', which
    would turn the pin gate off entirely and silently.
    """
    assert _ignored_by_git(tmp_path / "not-a-repo", ["docs/anything.md"]) == set()


# --- the gate itself still fires ---------------------------------------------

def test_extras_still_fail_the_gate():
    row = evaluate_pin(source_commit="a" * 40, diff_paths=[], extra_paths=["docs/stray.md"])
    assert row["ok"] is False
    assert any("unpinned_extra" in f for f in row["firing"])


def test_tracked_content_drift_still_fails_the_gate():
    """Exempting ignored EXTRAS must not soften tracked-file DIFFS."""
    row = evaluate_pin(source_commit="a" * 40, diff_paths=["scripts/api_v2.py"], extra_paths=[])
    assert row["ok"] is False


def test_clean_tree_passes():
    row = evaluate_pin(source_commit="a" * 40, diff_paths=[], extra_paths=[])
    assert row["ok"] is True
