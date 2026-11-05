"""FQ-152 — a heartbeat may only stamp a HEAD that belongs to the claim's own branch (claude-lead, 2026-11-05).

Before this, `agent_claim.py heartbeat` stamped `git rev-parse HEAD` of whatever tree the caller happened to be in.
Measured across the board: of 152 claims heartbeated in 24 h, 61 sat at their branch tip, 81 were behind it — 67 of
those claiming paths that had changed since, so they no longer describe what is being pushed — and 9 carried a head
from another branch entirely. A claim that is not at the pushed head cannot satisfy a claim-at-head gate, and the
refusal reads downstream as "no claim exists" rather than "the claim is at the wrong commit".

Hermetic: git is a fake callable and the board is a fake object. No repository, claim directory or network is read.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import agent_claim as CLI  # noqa: E402

BRANCH = "wt/example-20261105"
TIP = "a" * 40
OLD = "b" * 40
FOREIGN = "c" * 40


class FakeGit:
    """Answers only the calls FQ-152 makes; anything else is a failure, like an unexpected network call."""

    def __init__(self, tip: str | None = TIP, ancestors=(), behind: int = 0, changed=()):
        self.tip = tip
        self.ancestors = set(ancestors)
        self.behind = behind
        self.changed = list(changed)
        self.calls: list[list[str]] = []

    def __call__(self, args, cwd=None, timeout=10):
        self.calls.append(list(args))
        if args[:3] == ["rev-parse", "--verify", "-q"]:
            return self.tip
        if args[:1] == ["merge-base"]:
            return "" if (args[2], args[3]) in self.ancestors else None
        if args[:2] == ["rev-list", "--count"]:
            return str(self.behind)
        if args[:1] == ["diff"]:
            return "\n".join(self.changed)
        if args[:2] == ["rev-parse", "HEAD"]:
            return self.tip
        return None


def _patch_git(monkeypatch, fake):
    monkeypatch.setattr(CLI, "_git", fake)
    return fake


# ── head_position: the four answers ────────────────────────────────────────────────────────────────────────────────

def test_a_head_at_the_branch_tip_is_at_tip(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP))
    pos = CLI.head_position(BRANCH, TIP, ["scripts/a.py"], "/repo")
    assert pos["position"] == "at_tip" and pos["commits_behind"] == 0 and pos["paths_changed"] == 0


def test_a_head_on_the_branch_but_behind_reports_how_far_and_whether_it_still_covers(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors={(OLD, BRANCH)}, behind=3, changed=["scripts/a.py", "scripts/b.py"]))
    pos = CLI.head_position(BRANCH, OLD, ["scripts/a.py"], "/repo")
    assert pos["position"] == "behind_tip"
    assert pos["commits_behind"] == 3
    # one of the two changed files is claimed: this claim no longer covers what the branch now carries
    assert pos["paths_changed"] == 1


def test_a_head_behind_the_tip_with_no_claimed_path_changed_still_covers(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors={(OLD, BRANCH)}, behind=2, changed=["docs/other.md"]))
    pos = CLI.head_position(BRANCH, OLD, ["scripts/a.py"], "/repo")
    assert pos["position"] == "behind_tip" and pos["paths_changed"] == 0


def test_a_head_that_is_not_on_the_branch_is_named_as_such(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors=()))
    pos = CLI.head_position(BRANCH, FOREIGN, ["scripts/a.py"], "/repo")
    assert pos["position"] == "not_on_branch" and pos["branch_tip"] == TIP


def test_no_branch_tip_is_unresolved_rather_than_guessed(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=None))
    assert CLI.head_position(BRANCH, OLD, [], "/repo")["position"] == "unresolved"
    assert CLI.head_position(None, OLD, [], "/repo")["position"] == "unresolved"
    assert CLI.head_position(BRANCH, None, [], "/repo")["position"] == "unresolved"


# ── heartbeat_head_guard: what gets stamped, and what is said ───────────────────────────────────────────────────────

def test_a_foreign_head_is_never_stamped_and_is_warned_about(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors=()))
    guard = CLI.heartbeat_head_guard(BRANCH, FOREIGN, ["scripts/a.py"], "/repo", claim_id="C1")
    assert guard["stamp"] is None, "a heartbeat must not overwrite the claim with another branch's commit"
    assert guard["refuse"] is False, "warn by default: nineteen sessions share this tool"
    assert len(guard["warnings"]) == 1 and "not on claim C1's branch" in guard["warnings"][0]


def test_the_strict_form_refuses_instead_of_warning(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors=()))
    guard = CLI.heartbeat_head_guard(BRANCH, FOREIGN, [], "/repo", claim_id="C1", strict=True)
    assert guard["refuse"] is True and guard["stamp"] is None and guard["warnings"]


def test_a_behind_head_whose_claimed_path_changed_warns_that_it_no_longer_covers(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors={(OLD, BRANCH)}, behind=4, changed=["scripts/a.py"]))
    guard = CLI.heartbeat_head_guard(BRANCH, OLD, ["scripts/a.py"], "/repo", claim_id="C1")
    assert guard["stamp"] == OLD, "the head is on the branch, so it is honest to stamp it"
    assert len(guard["warnings"]) == 1 and "no longer covers the branch" in guard["warnings"][0]
    assert "4 commit(s) behind" in guard["warnings"][0]


def test_a_behind_head_that_still_covers_is_silent(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP, ancestors={(OLD, BRANCH)}, behind=4, changed=["docs/x.md"]))
    guard = CLI.heartbeat_head_guard(BRANCH, OLD, ["scripts/a.py"], "/repo", claim_id="C1")
    assert guard["warnings"] == [] and guard["refuse"] is False and guard["stamp"] == OLD


def test_a_head_at_the_tip_is_stamped_silently(monkeypatch):
    _patch_git(monkeypatch, FakeGit(tip=TIP))
    guard = CLI.heartbeat_head_guard(BRANCH, TIP, ["scripts/a.py"], "/repo")
    assert guard["stamp"] == TIP and guard["warnings"] == [] and guard["refuse"] is False


# ── the board-level count: the decay must stay visible without re-measuring by hand ────────────────────────────────

class FakeBoard:
    """`board.views()` is not consulted; `board()` and `get()` are all cmd_status needs from here."""

    def __init__(self, docs):
        self.docs = docs

    def refresh_claims(self, write: bool = False):
        return None

    def board(self, *, include_finished=True, limit=200, lifecycle_meta=None):
        claims = [
            {"claim_id": d["claim_id"], "state": "live", "stage": "building", "vendor": "claude", "agent": "worker",
             "branch": d.get("branch"), "head_sha": d.get("head_sha"), "task": "t", "worktree": None,
             "age_minutes": 5, "worklog": {"exists": False}}
            for d in self.docs
        ]
        return {"claims": claims, "as_of": "2026-11-05T00:00:00Z", "claims_dir": "/claims", "lifecycle": {}}

    def get(self, claim_id):
        for d in self.docs:
            if d["claim_id"] == claim_id:
                return types.SimpleNamespace(doc=d)
        raise KeyError(claim_id)


def test_status_prints_the_three_way_split(monkeypatch, capsys):
    docs = [
        {"claim_id": "C-at", "branch": BRANCH, "head_sha": TIP, "paths": ["scripts/a.py"]},
        {"claim_id": "C-behind-covers", "branch": BRANCH, "head_sha": OLD, "paths": ["scripts/a.py"]},
        {"claim_id": "C-behind-blind", "branch": BRANCH, "head_sha": OLD, "paths": ["scripts/a.py"]},
        {"claim_id": "C-off", "branch": BRANCH, "head_sha": FOREIGN, "paths": ["scripts/a.py"]},
    ]
    # one fake git per distinct situation, keyed by the subject under test
    def fake(args, cwd=None, timeout=10):
        if args[:3] == ["rev-parse", "--verify", "-q"]:
            return TIP
        if args[:1] == ["merge-base"]:
            return "" if args[2] == OLD else None
        if args[:2] == ["rev-list", "--count"]:
            return "3"
        if args[:1] == ["diff"]:
            return "scripts/a.py"
        return None

    monkeypatch.setattr(CLI, "_git", fake)
    monkeypatch.setattr(CLI, "_board", lambda a: FakeBoard(docs))
    monkeypatch.setattr(CLI, "_local_only_branches", lambda cwd, days, limit: [])
    monkeypatch.setattr(CLI, "_open_pr_branches", lambda timeout_s: (set(), None))
    a = types.SimpleNamespace(json=True, no_observe=True, repo=None, days=7, limit=50, no_gh_global=True)
    assert CLI.cmd_status(a) == 0
    out = json.loads(capsys.readouterr().out)
    hc = out["head_coverage"]
    assert hc["live_claims"] == 4
    assert hc["at_tip"] == 1
    assert hc["behind_tip"] == 2
    assert hc["behind_tip_no_longer_covering"] == 2, "both behind claims name a path that changed"
    assert hc["not_on_branch"] == 1
    assert hc["unresolved"] == 0
