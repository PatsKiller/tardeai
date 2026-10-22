"""Push budget v2 (2026-10-21, Release Train v2 Phase 0 item 3): the counter is keyed on
`git rev-parse --git-common-dir` plus the PUSHED branch (from the pre-push stdin refs), so a new
worktree or a branch switch cannot reset it; v1 counter files are read-only floors; a guard grant
lifts the cap only when its reason says "override"."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import tradeai_push_budget as B  # noqa: E402

SHA1 = "1" * 40
SHA2 = "2" * 40


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("TRADEAI_PUSH_BUDGET_PATH", raising=False)
    src = tmp_path / "main"
    src.mkdir()
    _git(src, "init", "-q", "-b", "main")
    _git(src, "config", "user.email", "t@t.local")
    _git(src, "config", "user.name", "t")
    (src / "f").write_text("x\n")
    _git(src, "add", "f")
    _git(src, "commit", "-qm", "init")
    _git(src, "branch", "feature/x")
    monkeypatch.chdir(src)
    return src


def _worktree(repo: Path, name: str, branch: str) -> Path:
    wt = repo.parent / name
    _git(repo, "worktree", "add", "-q", "-b", branch, str(wt))
    return wt


def test_counter_is_shared_by_every_worktree(repo, monkeypatch):
    B.record_authorized_push("feature/x")
    B.record_authorized_push("feature/x")
    wt = _worktree(repo, "wt2", "other")
    monkeypatch.chdir(wt)
    assert B.common_dir() == (repo / ".git").resolve()
    assert B.state_path() == (repo / ".git" / B.STATE_NAME_V2).resolve()
    assert B.count_for("feature/x") == 2
    blocked = B.decide_push(["feature/x"], authorized=True, env_override=False)
    assert blocked["allow"] is False and blocked["reason"] == "BUDGET_EXCEEDED" and blocked["branch"] == "feature/x"
    # A brand-new worktree checked out ON that branch sees the same count (v1 started it at 0).
    wt3 = repo.parent / "wt3"
    _git(repo, "worktree", "add", "-q", str(wt3), "feature/x")
    monkeypatch.chdir(wt3)
    assert B.load_state()["tranche_id"] == "feature/x" and B.load_state()["authorized_push_count"] == 2


def test_branch_switch_does_not_reset(repo):
    B.record_authorized_push("main")
    B.record_authorized_push("main")
    _git(repo, "checkout", "-q", "feature/x")
    assert B.count_for("main") == 2
    assert B.load_state("main")["authorized_push_count"] == 2
    assert B.count_for("feature/x") == 0


def test_counter_key_is_common_dir_plus_branch(repo):
    rec = B.record_authorized_push("feature/x", sha=SHA1)
    assert rec["counter_key"] == f"{(repo / '.git').resolve()}#feature/x"
    data = json.loads((repo / ".git" / B.STATE_NAME_V2).read_text())
    assert data["schema"] == B.SCHEMA_V2
    assert data["counters"][rec["counter_key"]]["last_sha"] == SHA1


def test_pushed_branch_comes_from_stdin_refs_not_head(repo):
    stdin = f"refs/heads/main {SHA1} refs/heads/feature/x {SHA2}\n"
    assert B.pushed_branches(stdin) == ["feature/x"]          # HEAD is main; the push writes feature/x
    multi = stdin + f"refs/heads/main {SHA1} refs/heads/main {SHA2}\nrefs/tags/v1 {SHA1} refs/tags/v1 {B.ZERO_SHA}\n"
    assert B.pushed_branches(multi) == ["feature/x", "main", "refs/tags/v1"]
    deletion = B.parse_push_refs(f"(delete) {B.ZERO_SHA} refs/heads/gone {SHA1}\n")[0]
    assert deletion["delete"] is True and deletion["branch"] == "gone"
    assert B.pushed_branches("") == ["main"]                  # no refs: HEAD fallback only
    assert B.pushed_branches("garbage line\n") == ["main"]


def test_every_pushed_branch_must_be_within_budget(repo):
    for _ in range(2):
        B.record_authorized_push("feature/x")
    d = B.decide_push(["main", "feature/x"], authorized=True, env_override=False)
    assert d["allow"] is False and d["branch"] == "feature/x"
    assert [x["allow"] for x in d["branches"]] == [True, False]


def test_v1_files_are_read_only_floors(repo, monkeypatch):
    v1_main = repo / ".git" / B.STATE_NAME
    v1_main.write_text(json.dumps({"tranche_id": "feature/x", "authorized_push_count": 1}))
    wt = _worktree(repo, "wt2", "other")
    wt_gitdir = Path(_git(wt, "rev-parse", "--absolute-git-dir"))
    v1_wt = wt_gitdir / B.STATE_NAME
    v1_wt.write_text(json.dumps({"tranche_id": "feature/x", "authorized_push_count": 1, "last_branch": "feature/x"}))
    before = (v1_main.read_bytes(), v1_wt.read_bytes())
    assert B.legacy_counts() == {"feature/x": 2}
    assert B.count_for("feature/x") == 2
    assert B.decide_push(["feature/x"], authorized=True, env_override=False)["allow"] is False
    B.record_authorized_push("main")
    assert (v1_main.read_bytes(), v1_wt.read_bytes()) == before  # never rewritten, never removed
    monkeypatch.chdir(wt)
    assert B.count_for("feature/x") == 2


def test_override_file_holding_v1_content_carries_its_count(repo, tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    path.write_text(json.dumps({"tranche_id": "main", "authorized_push_count": 1}))
    monkeypatch.setenv("TRADEAI_PUSH_BUDGET_PATH", str(path))
    assert B.count_for("main") == 1
    B.record_authorized_push("main")
    assert B.count_for("main") == 2
    assert json.loads(path.read_text())["schema"] == B.SCHEMA_V2


@pytest.mark.parametrize("reason,expected", [
    ("push wt/x, budget override approved by operator", True),
    ("OVERRIDE push budget for wt/x", True),
    ("push wt/x (override)", True),
    ("push wt/x", False),
    ("overrides nothing", False),
    ("nooverride", False),
    ("", False),
    (None, False),
])
def test_grant_reason_override_word(reason, expected):
    assert B.grant_overrides_budget(reason) is expected


def test_guard_grant_without_override_word_is_capped(repo):
    for _ in range(2):
        B.record_authorized_push("main")
    plain = B.decide_push(["main"], authorized=True, env_override=False, grant_reason="push main")
    assert plain["allow"] is False and plain["override"] is False
    over = B.decide_push(["main"], authorized=True, env_override=False, grant_reason="push main override")
    assert over["allow"] is True and over["reason"] == "OVERRIDE" and over["override_source"] == "grant_reason"
    env = B.decide_push(["main"], authorized=True, env_override=True)
    assert env["allow"] is True and env["override_source"] == "env"
    unauth = B.decide_push(["main"], authorized=False, env_override=True, grant_reason="override")
    assert unauth["allow"] is False and unauth["reason"] == "UNAUTHORIZED"


def test_concurrent_records_are_not_lost(repo):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: B.record_authorized_push("main"), range(16)))
    assert B.count_for("main") == 16


def test_v1_api_still_answers(repo):
    st = B.load_state()
    assert st["tranche_id"] == "main" and st["authorized_push_count"] == 0
    B.record_authorized_push()
    assert B.load_state()["authorized_push_count"] == 1
    assert B.remaining(1) == 1 and B.MAX_WITHOUT_OVERRIDE == 2
