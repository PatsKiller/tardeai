"""Claim board shared-additive paths (2026-10-23): docs/INDEX.md and friends never conflict.

Two sessions may both claim docs/INDEX.md; an exclusive file still conflicts; ``check`` reports a shared path clear;
``take`` of a task whose areas include a shared path is not refused; the pre-commit gate treats a staged shared file
as covered by any own claim but still requires a claim for the rest of the change. Hermetic: temp dirs, no gh.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import agent_claim as CLI  # noqa: E402
from scripts.lib import agent_claim_board as B  # noqa: E402

T0 = datetime(2026, 10, 23, 18, 0, tzinfo=timezone.utc)
SHARED = (
    "docs/INDEX.md",
    "docs/DOCUMENTATION_INDEX.md",
    "apps/command-center-v3/package.json",
    "DOCS_AND_AGENTS_UPDATE_BACKLOG.md",
)


@pytest.fixture(autouse=True)
def _real_config(monkeypatch):
    monkeypatch.delenv(B.ENV_SHARED, raising=False)


def board(tmp_path: Path) -> B.ClaimBoard:
    return B.ClaimBoard(tmp_path / "claims", now=lambda: T0)


def mk(b, session, paths):
    return b.claim(vendor="claude", session=session, agent=None, task="t", paths=paths, branch=f"feat/{session}")


def agents_md(tmp_path, version="20.1.0"):
    p = tmp_path / "AGENTS.md"
    p.write_text(
        f"```\nPolicy-Version:      {version}\nStatus:              ACTIVE\n```\n\n"
        f"| Version | Date | Status | Class | S | A |\n|---|---|---|---|---|---|\n| {version} | d | ACTIVE | MAJOR | s | a |\n"
    )
    return p


def test_shipped_config_lists_the_shared_paths_with_merge_strategy():
    doc = json.loads((ROOT / "config" / "agent_claim_shared_paths.json").read_text())
    assert doc["schema"] == B.SHARED_SCHEMA
    entries = B.shared_path_entries()
    for p in SHARED:
        assert p in entries, p
        assert entries[p]["merge"] and entries[p]["reason"]
    assert entries["docs/INDEX.md"]["merge"] == "regenerate"
    assert entries["apps/command-center-v3/package.json"]["merge"] == "union_build"
    assert entries["DOCS_AND_AGENTS_UPDATE_BACKLOG.md"]["merge"] == "append rows"
    assert "~/n8n-maturity-verification/DOCS_AND_AGENTS_UPDATE_BACKLOG.md" in entries
    assert not any(B.is_glob(p) for p in entries)


def test_two_sessions_both_claim_index_while_exclusive_file_still_conflicts(tmp_path):
    b = board(tmp_path)
    mk(b, "s1", ["docs/INDEX.md", "scripts/x.py"])
    d2 = mk(b, "s2", ["docs/INDEX.md", "docs/ops/Y.md"])  # shared overlap only: no conflict
    assert d2["status"] == "active"
    with pytest.raises(B.ClaimConflict) as ei:
        mk(b, "s3", ["docs/INDEX.md", "scripts/x.py"])
    held = {o["held"] for r in ei.value.conflicts for o in r["overlaps"]}
    assert held == {"scripts/x.py"}  # INDEX.md is never reported as a conflict


@pytest.mark.parametrize("p", SHARED)
def test_every_shared_path_never_conflicts(tmp_path, p):
    b = board(tmp_path)
    mk(b, "s1", [p])
    mk(b, "s2", [p])
    assert b.conflicts([p], session="s3") == []


def test_directory_claim_does_not_collide_with_shared_file(tmp_path):
    b = board(tmp_path)
    mk(b, "s1", ["docs/INDEX.md"])
    mk(b, "s2", ["docs/**"])  # broad claim, but the only overlap is the shared file
    assert b.conflicts(["docs/ops/Z.md"], session="s3")  # docs/** is still exclusive for everything else


def test_missing_config_means_exclusive(tmp_path, monkeypatch):
    monkeypatch.setenv(B.ENV_SHARED, str(tmp_path / "absent.json"))
    b = board(tmp_path)
    mk(b, "s1", ["docs/INDEX.md"])
    with pytest.raises(B.ClaimConflict):
        mk(b, "s2", ["docs/INDEX.md"])


def test_glob_entries_in_config_are_ignored(tmp_path, monkeypatch):
    cfg = tmp_path / "shared.json"
    cfg.write_text(json.dumps({"schema": B.SHARED_SCHEMA, "paths": [{"path": "docs/**", "merge": "x"}]}))
    monkeypatch.setenv(B.ENV_SHARED, str(cfg))
    assert B.shared_paths() == frozenset()


def test_cli_check_and_claim(tmp_path, capsys):
    cd = str(tmp_path / "claims")
    base = ["--claims-dir", cd, "--vendor", "claude"]
    assert (
        CLI.main(
            base
            + [
                "--session",
                "s1",
                "claim",
                "--task",
                "a",
                "--paths",
                "docs/INDEX.md",
                "scripts/x.py",
                "--branch",
                "feat/s1",
            ]
        )
        == 0
    )
    assert (
        CLI.main(base + ["--session", "s2", "claim", "--task", "b", "--paths", "docs/INDEX.md", "--branch", "feat/s2"])
        == 0
    )
    assert "shared (never conflicts" in capsys.readouterr().err
    assert (
        CLI.main(
            base + ["--session", "s3", "check", "--no-gh", "--exclude-branch", "feat/s3", "--paths", "docs/INDEX.md"]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "clear" in out and "docs/INDEX.md [merge: regenerate]" in out
    assert (
        CLI.main(
            base + ["--session", "s3", "check", "--no-gh", "--exclude-branch", "feat/s3", "--paths", "scripts/x.py"]
        )
        == 1
    )
    capsys.readouterr()
    assert CLI.main(base + ["list"]) == 0
    assert "docs/INDEX.md (shared)" in capsys.readouterr().out


def test_board_view_marks_shared(tmp_path):
    b = board(tmp_path)
    mk(b, "s1", ["docs/INDEX.md", "scripts/x.py"])
    view = b.board()
    assert "docs/INDEX.md" in view["shared_paths"]
    assert view["claims"][0]["shared_paths"] == ["docs/INDEX.md"]


def test_take_task_with_shared_area_is_not_refused(tmp_path):
    from scripts.lib import agent_task_board as TB

    b = board(tmp_path)
    mk(b, "holder", ["docs/INDEX.md"])
    tb = TB.TaskBoard(b)
    t = tb.add(title="x", kind="fix", areas=["docs/INDEX.md", "scripts/y.py"])
    taken = tb.next(vendor="claude", session="s2", agent=None, branch="feat/s2", task_id=t["task_id"])
    assert taken is not None


def _own_with_plan(b, session, paths):
    d = mk(b, session, paths)
    b.worklog(d["claim_id"]).create(d, goal="g", request="operator: g", plan=["step"], worktree="/wt/x")
    return d


def test_precommit_shared_file_covered_by_any_own_claim_rest_still_required(tmp_path):
    b = board(tmp_path)
    md = agents_md(tmp_path)
    mk(b, "other", ["docs/INDEX.md"])  # another session holds INDEX.md: never blocks
    gate = lambda paths, session="s1": B.precommit_gate(  # noqa: E731
        b, paths, session=session, vendor="claude", branch=f"feat/{session}", agents_md=md
    )
    # No claim at all: the shared file alone still needs the committer to hold a claim.
    res = gate(["docs/INDEX.md"])
    assert res["exit_code"] == 1 and res["uncovered"] == ["docs/INDEX.md"] and not res["conflicts"]
    _own_with_plan(b, "s1", ["scripts/z.py"])
    res = gate(["docs/INDEX.md", "scripts/z.py"])
    assert res["exit_code"] == 0, res["messages"]
    res = gate(["docs/INDEX.md", "scripts/z.py", "scripts/unclaimed.py"])
    assert res["exit_code"] == 1 and res["uncovered"] == ["scripts/unclaimed.py"]
