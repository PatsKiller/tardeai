"""Per-claim worklog, takeover, status and SHA recording (operator 2026-10-23): hermetic, temp dirs + temp git repos.

Covers: worklog created by `claim` with the 7 fixed sections; plan/done/note/blocker/handoff append with times and
check off steps; stage changes (declared and observed) append to Status; release needs a final summary; compaction
moves the worklog to worklog_archive/ (never deleted); the pre-commit gate's worklog freshness (warn below AGENTS.md
20.0.0, block from it); the API worklog read; takeover prints Handoff first and carries the history forward;
heartbeat records the head SHA and appends new commits; status lists in-flight claims and local-only work at risk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import agent_claim as CLI  # noqa: E402
from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_claim_lifecycle as LC  # noqa: E402
from scripts.lib import agent_claim_worklog as WL  # noqa: E402

T0 = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
GITENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@x",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@x",
}


class Clock:
    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t = self.t + timedelta(**kw)


def board(tmp_path, clock=None):
    return B.ClaimBoard(tmp_path / "claims", now=clock or Clock())


def mkw(b, session="s1", paths=("docs/a.md",), plan=("write code", "write tests"), **kw):
    d = b.claim(
        vendor="claude",
        session=session,
        agent="w",
        task="do X",
        paths=list(paths),
        branch=kw.get("branch", f"feat/{session}"),
        pr=kw.get("pr"),
    )
    b.worklog(d["claim_id"]).create(d, goal="do X well", request="operator: do X", plan=list(plan), worktree="/wt/x")
    return d


def cli(tmp_path, *args, session="s1", vendor="claude"):
    return CLI.main(
        ["--claims-dir", str(tmp_path / "claims"), "--no-gh", "--session", session, "--vendor", vendor, *args]
    )


def git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env={**os.environ, **GITENV}
    ).stdout.strip()


# ------------------------------------------------------------------------------------------- worklog file


def test_worklog_has_the_seven_sections_in_order(tmp_path):
    b = board(tmp_path)
    d = mkw(b)
    text = WL.path_for(b.dir, d["claim_id"]).read_text()
    heads = [ln[3:] for ln in text.splitlines() if ln.startswith("## ")]
    assert heads == ["Goal", "Plan", "Changes made", "Decisions", "Blockers", "Status", "Handoff"]
    assert "> operator: do X" in text and "- [ ] write code" in text and "Worktree: `/wt/x`" in text
    with pytest.raises(FileExistsError):  # never overwritten
        b.worklog(d["claim_id"]).create(d)


def test_plan_done_note_blocker_handoff(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mkw(b)
    wl = b.worklog(d["claim_id"])
    clock.advance(minutes=5)
    wl.plan("update docs")
    assert wl.done("tests") == "write tests"  # unique substring
    wl.note("chose flock over sqlite: no new store")
    wl.note("scripts/x.py edited", change=True)
    wl.blocker("needs operator approval of 20.0.0 (operator)")
    wl.handoff(next_step="run pytest tests/x.py", verify="CI green")
    s = WL.summarize(wl.read())
    assert (s["plan_total"], s["plan_done"]) == (3, 1)
    assert s["blockers"] == 1 and s["next_step"].startswith("run pytest tests/x.py")
    assert s["last_entry_at"] == "2026-10-23T14:05:00Z"
    text = wl.read()
    assert "- [x] write tests  _(added 2026-10-23T14:00:00Z)_  _(done 2026-10-23T14:05:00Z)_" in text
    assert "`2026-10-23T14:05:00Z` chose flock" in text.split("## Decisions")[1].split("## Blockers")[0]
    assert "scripts/x.py edited" in text.split("## Changes made")[1].split("## Decisions")[0]
    wl.done("an unplanned step")  # unknown step is added already checked
    assert WL.summarize(wl.read())["plan_done"] == 2
    wl.plan("write more")
    with pytest.raises(WL.WorklogError, match="match"):
        wl.done("write")  # ambiguous


def test_cli_worklog_commands_resolve_the_sessions_claim(tmp_path, capsys):
    assert (
        cli(
            tmp_path,
            "claim",
            "--task",
            "t",
            "--paths",
            "docs/a.md",
            "--branch",
            "b1",
            "--plan",
            "one",
            "two",
            "--request",
            "operator said so",
        )
        == 0
    )
    cid = capsys.readouterr().out.strip().splitlines()[-1]
    assert cli(tmp_path, "plan", "three") == 0
    assert cli(tmp_path, "done", "one") == 0
    assert cli(tmp_path, "note", "because") == 0
    assert cli(tmp_path, "blocker", "waiting on codex") == 0
    assert cli(tmp_path, "handoff", "--next", "finish two", "--verify", "pytest") == 0
    assert cli(tmp_path, "plan", "x", session="other") == 2  # not its claim
    s = WL.summarize(WL.path_for(tmp_path / "claims", cid).read_text())
    assert (s["plan_total"], s["plan_done"], s["blockers"]) == (3, 1, 1)


def test_stage_changes_append_to_status_declared_and_observed(tmp_path):
    b = board(tmp_path)
    d = mkw(b, pr=None)
    b.stage(d["claim_id"], "building", session="s1")
    b.stage(d["claim_id"], "pr_open", session="s1", pr="7")

    class GH:
        def __call__(self, cmd, **kw):
            pr = {
                "number": 7,
                "state": "closed",
                "merged_at": "2026-10-23T16:00:00Z",
                "merge_commit_sha": "b" * 40,
                "created_at": "2026-10-23T14:05:00Z",
                "html_url": "u",
                "base": {"ref": "main"},
                "head": {"sha": "a" * 40},
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(pr), stderr="")

    b.observer = LC.LifecycleObserver(LC.GitHubReader("o/r", runner=GH()), None, now=Clock())
    b.refresh_claims()
    status = WL.parse(b.worklog(d["claim_id"]).read())[1]["Status"]
    joined = "\n".join(status)
    assert "stage building" in joined and "stage pr_open (PR 7)" in joined
    assert "stage merged observed (PR #7 merge bbbbbbbbb)  (auto)" in joined
    # observed entries do not count as the agent's own activity
    assert WL.summarize(b.worklog(d["claim_id"]).read())["last_entry_at"] == "2026-10-23T14:00:00Z"


def test_release_requires_final_summary(tmp_path, capsys):
    assert cli(tmp_path, "claim", "--task", "t", "--paths", "docs/a.md", "--branch", "b1", "--plan", "x") == 0
    cid = capsys.readouterr().out.strip().splitlines()[-1]
    assert cli(tmp_path, "release", cid) == 2
    assert "final summary" in capsys.readouterr().err
    assert cli(tmp_path, "release", cid, "--summary", "shipped X in PR 7") == 0
    s = WL.summarize(WL.path_for(tmp_path / "claims", cid).read_text())
    assert s["final_summary"] == "shipped X in PR 7"


def test_compaction_archives_worklog_never_deletes(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mkw(b)
    b.release(d["claim_id"], session="s1", summary="done")
    clock.advance(days=8)
    res = b.compact(apply=True)
    assert res["removed"] == 1
    arch = WL.archive_dir(b.dir) / f"{d['claim_id']}{WL.SUFFIX}"
    assert arch.is_file() and not WL.path_for(b.dir, d["claim_id"]).exists()
    line = json.loads((b.dir / B.HISTORY_NAME).read_text().splitlines()[-1])
    assert line["worklog_archive"] == str(arch)
    assert res["worklogs_archived"][0]["sha256"]
    view = B.board_view(b.dir, worklog=d["claim_id"], observer=LC.CachedObserver(lambda: None))
    assert view["found"] and view["path"] == str(arch) and "Final summary: done" in view["text"]


def test_api_worklog_read_and_bad_id(tmp_path):
    b = board(tmp_path)
    d = mkw(b)
    out = B.board_view(b.dir, worklog=d["claim_id"])
    assert out["found"] and out["summary"]["plan_total"] == 2 and "## Handoff" in out["text"]
    assert B.board_view(b.dir, worklog="../../etc/passwd")["found"] is False
    cache = LC.CachedObserver(lambda: LC.LifecycleObserver(None, None))
    row = B.board_view(b.dir, observer=cache, background=False)["claims"][0]
    assert row["worklog"]["plan_total"] == 2 and row["worklog"]["exists"] is True


# ------------------------------------------------------------------------------------------- gate freshness


def agents_md(tmp_path, version):
    p = tmp_path / f"AGENTS-{version}.md"
    p.write_text(
        f"```\nPolicy-Version:      {version}\nStatus:              ACTIVE\n```\n\n"
        f"| Version | Date | Status | Class | S | A |\n|---|---|---|---|---|---|\n| {version} | d | ACTIVE | MAJOR | s | a |\n"
    )
    return p


@pytest.mark.parametrize("version,rc", [("19.0.0", 0), ("20.0.0", 1)])
def test_gate_refuses_claim_without_plan_or_fresh_entry(tmp_path, version, rc):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mkw(b, plan=())  # no plan
    gate = lambda: B.precommit_gate(
        b,
        ["docs/a.md"],
        session="s1",
        vendor="claude",
        branch="feat/s1",  # noqa: E731
        agents_md=agents_md(tmp_path, version),
    )
    res = gate()
    assert res["exit_code"] == rc and "no plan" in res["worklog_issues"][0]["issue"]
    b.worklog(d["claim_id"]).plan("step")
    assert gate()["exit_code"] == 0
    clock.advance(hours=3)
    res = gate()
    assert res["exit_code"] == rc and "last 2 h" in res["worklog_issues"][0]["issue"]
    b.worklog(d["claim_id"]).note("still going")
    assert gate()["exit_code"] == 0


def test_gate_refuses_claim_without_worklog_at_20(tmp_path):
    b = board(tmp_path)
    b.claim(vendor="claude", session="s1", agent=None, task="t", paths=["docs/a.md"], branch="feat/s1")
    res = B.precommit_gate(
        b, ["docs/a.md"], session="s1", vendor="claude", branch="feat/s1", agents_md=agents_md(tmp_path, "20.0.0")
    )
    assert res["exit_code"] == 1 and res["worklog_issues"][0]["issue"] == "has no worklog"


# ------------------------------------------------------------------------------------------- git: SHAs, status, takeover


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "a.txt").write_text("1")
    git(r, "add", "a.txt")
    git(r, "commit", "-q", "-m", "base")
    git(r, "remote", "add", "origin", str(remote))
    git(r, "push", "-q", "origin", "main")
    git(r, "checkout", "-q", "-b", "feat/w")
    monkeypatch.chdir(r)
    for k, v in GITENV.items():
        monkeypatch.setenv(k, v)
    return r


def test_claim_and_heartbeat_record_sha_and_append_commits(tmp_path, repo, capsys):
    assert cli(tmp_path, "claim", "--task", "t", "--paths", "a.txt", "--plan", "p") == 0
    cid = capsys.readouterr().out.strip().splitlines()[-1]
    doc = json.loads((tmp_path / "claims" / f"{cid}.json").read_text())
    base = git(repo, "rev-parse", "HEAD")
    assert doc["head_sha"] == base and doc["worktree"] == str(repo) and doc["logged_sha"] == base
    for i in range(2):
        (repo / "a.txt").write_text(str(i + 2))
        git(repo, "commit", "-q", "-am", f"change {i}")
    head = git(repo, "rev-parse", "HEAD")
    assert cli(tmp_path, "heartbeat", cid) == 0
    doc = json.loads((tmp_path / "claims" / f"{cid}.json").read_text())
    assert doc["head_sha"] == head and doc["logged_sha"] == head and doc["head_sha_at"]
    changes = "\n".join(WL.parse(WL.path_for(tmp_path / "claims", cid).read_text())[1]["Changes made"])
    assert "change 0" in changes and "change 1" in changes and "base" not in changes
    assert cli(tmp_path, "heartbeat", cid) == 0  # nothing new: nothing appended
    again = "\n".join(WL.parse(WL.path_for(tmp_path / "claims", cid).read_text())[1]["Changes made"])
    assert again == changes


def test_status_lists_in_flight_and_local_only_work(tmp_path, repo, capsys):
    assert cli(tmp_path, "claim", "--task", "t", "--paths", "a.txt", "--plan", "p") == 0
    capsys.readouterr()
    (repo / "a.txt").write_text("local")
    git(repo, "commit", "-q", "-am", "local only")
    git(repo, "branch", "pushed-copy", "main")
    assert cli(tmp_path, "status", "--json", "--no-observe", "--repo", str(repo)) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["branch"] for r in out["in_flight"]] == ["feat/w"]
    assert out["in_flight"][0]["live_head_sha"] == git(repo, "rev-parse", "HEAD")
    risk = {r["branch"]: r for r in out["local_only_at_risk"]}
    assert "feat/w" in risk and risk["feat/w"]["unpushed_commits"] == 1
    assert "pushed-copy" not in risk and "main" not in risk
    assert cli(tmp_path, "status", "--no-observe", "--repo", str(repo)) == 0
    text = capsys.readouterr().out
    assert "## In flight (1)" in text and "Local-only work at risk (1)" in text and "handoff:" in text


def test_takeover_prints_handoff_first_and_carries_history(tmp_path, repo, capsys):
    clock_board = B.ClaimBoard(tmp_path / "claims")
    assert cli(tmp_path, "claim", "--task", "t", "--paths", "a.txt", "--plan", "p1", "p2", session="old") == 0
    cid = capsys.readouterr().out.strip().splitlines()[-1]
    assert cli(tmp_path, "handoff", "--next", "finish p2", "--verify", "pytest", session="old") == 0
    assert cli(tmp_path, "done", "p1", session="old") == 0
    capsys.readouterr()
    assert cli(tmp_path, "takeover", cid, session="new", vendor="codex") == 0
    out = capsys.readouterr().out
    assert out.startswith("## Handoff") and "finish p2" in out and "- [ ] p2" in out and str(repo) in out
    # live claim: taking over is refused until it is released / stale / merged
    assert cli(tmp_path, "takeover", cid, "--claim", session="new", vendor="codex") == 1
    capsys.readouterr()
    assert cli(tmp_path, "release", cid, "--summary", "handing to codex", session="old") == 0
    assert cli(tmp_path, "takeover", cid, "--claim", session="new", vendor="codex") == 0
    new_id = capsys.readouterr().out.strip().splitlines()[-1].split()[0]
    new_text = WL.path_for(tmp_path / "claims", new_id).read_text()
    assert "- [x] p1" in new_text and "- [ ] p2" in new_text and "finish p2" in new_text  # history carried
    assert "taken over by codex/new at" in new_text and f"from claude/old (claim {cid})" in new_text
    old_text = WL.path_for(tmp_path / "claims", cid).read_text()
    assert f"-> new claim {new_id}" in old_text
    assert clock_board.get(new_id).doc["paths"] == ["a.txt"]


def test_session_start_script_is_read_only_and_exits_0(tmp_path, repo):
    env = {**os.environ, "TRADEAI_AGENT_CLAIMS_DIR": str(tmp_path / "claims")}
    p = subprocess.run(
        ["bash", str(ROOT / "scripts" / "agent_session_start.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert p.returncode == 0 and "Agent claim board" in p.stdout
    assert not (tmp_path / "claims").exists()


def test_start_here_doc_and_adapters_exist():
    doc = (ROOT / "docs" / "ops" / "AGENT_START_HERE.md").read_text()
    for cmd in ("status", "next", "plan", "stage", "task done", "takeover", "TRADEAI_CLAIM_OVERRIDE"):
        assert cmd in doc
    assert (ROOT / "docs" / "ops" / "agent_start" / "cursor-rule.md").is_file()
    assert (ROOT / "docs" / "ops" / "agent_start" / "codex-note.md").is_file()
