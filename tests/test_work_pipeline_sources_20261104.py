"""BOARD row 78 (operator P0): the Work pipeline's sources must not lie.

Three live defects, each pinned here:
1. the PR census called ``gh`` with no repository, so from the release directory it failed with
   "fatal: not a git repository" and the pipeline's clock froze (last good value Oct 31);
2. a failed ``gh`` call reported only gh's stderr, not which command failed;
3. "231 QUEUED" collapsed three different ownership facts into one number.

Red first: each test below fails on the pre-fix code (no ``--repo`` in the argv; no command in the message; no
``queued_by_owner`` in the summary).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from lib import work_pipeline as W  # noqa: E402


def test_the_pr_census_names_the_repository_on_every_call():
    seen: list[list[str]] = []

    def runner(argv):
        seen.append(argv)
        if argv[:2] == ["gh", "pr"]:
            return "[]", None
        return '{"sha": "0123456789abcdef"}', None

    census = W.PrCensus(runner=runner, release=None)
    census._refresh()
    pr_calls = [a for a in seen if a[:3] in (["gh", "pr", "list"], ["gh", "pr", "view"])]
    assert pr_calls, "no gh pr call was made"
    for argv in pr_calls:
        assert "--repo" in argv, f"gh pr call without --repo: {argv}"
        assert argv[argv.index("--repo") + 1] == W.LC.default_repo()


def test_a_failed_gh_call_says_which_command_failed(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "fatal: not a git repository (or any of the parent directories)\n"

    monkeypatch.setattr(W.subprocess, "run", lambda *a, **k: Proc())
    out, warning = W._gh_runner(["gh", "pr", "list", "--repo", "PatsKiller/tardeai", "--state", "open"])
    assert out is None
    assert "gh exited 1" in warning and "--repo" in warning, warning
    assert "not a git repository" in warning


def _item(owner_kind: str) -> dict:
    return {"stage": "queued", "finished": False, "rag": "grey", "who": {"kind": owner_kind},
            "next": {"owner": "agent"}, "waiting_for_batch": False}


def test_the_queued_count_is_split_by_who_owns_it():
    items = [_item("operator")] * 38 + [_item("agent")] * 87 + [_item("none")] * 106
    summary = W.summarize(items)
    assert summary["counts"]["queued"] == 231
    assert summary["queued_by_owner"] == {"operator": 38, "agent": 87, "nobody": 106}, summary["queued_by_owner"]
