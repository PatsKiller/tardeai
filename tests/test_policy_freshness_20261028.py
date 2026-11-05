"""Policy freshness library and version-change broadcast (operator 2026-10-28).

scripts/lib/policy_freshness.py: OK / STALE / UNKNOWN, the branch-ahead exemption, offline fallback, CLI exit codes.
scripts/lib/policy_version_broadcast.py: baseline, broadcast (marks + one Telegram line), per-version dedupe, retry,
dry run writes nothing; agent_claim board rows and `status` show POLICY CHANGED until a heartbeat clears it.
Every repository here is a throwaway: a bare "origin" plus clones under tmp_path. No network, no real board.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.lib import agent_claim_board as B
from scripts.lib import policy_freshness as PF
from scripts.lib import policy_version_broadcast as PB

ROOT = Path(__file__).resolve().parents[1]


def agents_md(version: str, extra: str = "") -> str:
    return f"# AGENTS.md\n\n```\nPolicy-Version:      {version}\nStatus:              ACTIVE\n```\n\nRules.\n{extra}"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=60
    ).stdout.strip()


def commit_file(repo: Path, text: str, msg: str, name: str = "AGENTS.md") -> str:
    (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def _git_env(monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for k, v in (("NAME", "Policy Test"), ("EMAIL", "policy@test.local")):
        monkeypatch.setenv(f"GIT_AUTHOR_{k}", v)
        monkeypatch.setenv(f"GIT_COMMITTER_{k}", v)
    monkeypatch.setenv(PF.ENV_FETCH_TIMEOUT, "20")


@pytest.fixture
def world(tmp_path):
    """origin (bare) with main at 1.0.0; ``upstream`` pushes to it; ``agent`` is the agent's clone."""
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    up = tmp_path / "upstream"
    git(tmp_path, "clone", "-q", str(origin), str(up))
    git(up, "checkout", "-q", "-b", "main")
    commit_file(up, agents_md("1.0.0"), "policy 1.0.0")
    git(up, "push", "-q", "origin", "main")
    agent = tmp_path / "agent"
    git(tmp_path, "clone", "-q", str(origin), str(agent))

    def advance(version: str) -> str:
        sha = commit_file(up, agents_md(version), f"policy {version}")
        git(up, "push", "-q", "origin", "main")
        return sha

    return {"origin": origin, "up": up, "agent": agent, "advance": advance}


# ------------------------------------------------------------------------------------------- parsing


def test_parse_policy_version_and_semver_order():
    assert PF.parse_policy_version(agents_md("26.0.0")) == "26.0.0"
    assert PF.parse_policy_version("no control block") is None
    assert PF.parse_policy_version(None) is None
    assert PF.version_behind("25.0.1", "26.0.0") and PF.version_behind("26.0.0", "26.0.10")
    assert not PF.version_behind("26.0.0", "26.0.0") and not PF.version_behind("27.0.0", "26.0.0")
    assert not PF.version_behind("garbage", "26.0.0")


# ------------------------------------------------------------------------------------------- verdicts


def test_ok_when_blobs_match(world):
    r = PF.evaluate(world["agent"])
    assert r.status == PF.OK and r.exit_code == 0 and not r.offline and r.fetch == "fetched"
    assert r.local_blob == r.remote_blob and r.local_version == "1.0.0"
    assert "matches origin/main" in r.message()


def test_stale_after_main_moves_fetch_sees_it(world):
    assert PF.evaluate(world["agent"]).status == PF.OK
    world["advance"]("2.0.0")  # the agent's own origin/main ref is still old: only the fetch can reveal this
    r = PF.evaluate(world["agent"])
    assert r.status == PF.STALE and r.exit_code == 1
    assert r.message().startswith("STALE_POLICY: your AGENTS.md is 1.0.0, origin/main is 2.0.0; work from fresh")
    assert "scripts/new-worktree.sh" in r.message() and "re-read §0" in r.message()


def test_stale_never_hard_codes_a_version(world):
    world["advance"]("27.0.0")
    r = PF.evaluate(world["agent"])
    assert (r.status, r.local_version, r.remote_version) == (PF.STALE, "1.0.0", "27.0.0")


def test_unchanged_agents_md_is_ok_even_when_branch_is_behind(world):
    commit_file(world["up"], "other\n", "unrelated", name="README")
    git(world["up"], "push", "-q", "origin", "main")
    assert PF.evaluate(world["agent"]).status == PF.OK


def test_branch_editing_agents_md_on_top_of_main_is_exempt(world):
    world["advance"]("2.0.0")
    a = world["agent"]
    git(a, "pull", "-q", "origin", "main")
    git(a, "checkout", "-q", "-b", "policy-bump")
    commit_file(a, agents_md("3.0.0"), "bump to 3.0.0")
    r = PF.evaluate(a)
    assert r.status == PF.OK and r.exempt and "on top of origin/main's 2.0.0" in r.message()
    (a / "AGENTS.md").write_text(agents_md("3.0.0", "uncommitted edit\n"))  # worktree edit, same base: still ahead
    assert PF.evaluate(a, fetch=False).exempt


def test_downgrade_on_top_of_main_is_never_exempt(world):
    world["advance"]("2.0.0")
    a = world["agent"]
    git(a, "pull", "-q", "origin", "main")
    git(a, "checkout", "-q", "-b", "policy-downgrade")
    commit_file(a, agents_md("1.5.0"), "lower the version on top of 2.0.0")
    r = PF.evaluate(a)
    assert r.status == PF.STALE and not r.exempt
    assert (
        "your AGENTS.md is 1.5.0, origin/main is 2.0.0" in r.message() and "a downgrade is never exempt" in r.message()
    )


def test_equal_version_edit_on_top_of_main_stays_exempt(world):
    a = world["agent"]
    git(a, "checkout", "-q", "-b", "same-version-edit")
    commit_file(a, agents_md("1.0.0", "wording\n"), "edit, same version, on top of main")
    r = PF.evaluate(a)
    assert r.status == PF.OK and r.exempt


def test_unreadable_version_on_a_branch_editing_agents_md_is_stale(world):
    a = world["agent"]
    git(a, "checkout", "-q", "-b", "broken-header")
    commit_file(a, "# AGENTS.md without a control block\n", "drop the control block")
    r = PF.evaluate(a)
    assert r.status == PF.STALE and "readable Policy-Version" in r.message()


def test_bumping_branch_built_on_an_old_main_is_stale(world):
    a = world["agent"]
    git(a, "checkout", "-q", "-b", "policy-bump")
    commit_file(a, agents_md("3.0.0"), "bump to 3.0.0 on 1.0.0")
    world["advance"]("2.0.0")
    r = PF.evaluate(a)
    assert r.status == PF.STALE and not r.exempt
    assert "your AGENTS.md is 3.0.0, origin/main is 2.0.0" in r.message()


def test_same_version_different_text_is_stale(world):
    (world["up"] / "AGENTS.md").write_text(agents_md("1.0.0", "silent edit\n"))
    git(world["up"], "commit", "-qam", "edit without bump")
    git(world["up"], "push", "-q", "origin", "main")
    r = PF.evaluate(world["agent"])
    assert r.status == PF.STALE and "same version number, different text" in r.message()


# ------------------------------------------------------------------------------------------- unknown / offline


def test_unknown_without_origin_is_a_warning_not_a_pass(tmp_path):
    repo = tmp_path / "solo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    commit_file(repo, agents_md("1.0.0"), "init")
    r = PF.evaluate(repo)
    assert r.status == PF.UNKNOWN and r.exit_code == 3
    assert "UNKNOWN_POLICY" in r.message() and "a warning, not a pass" in r.message()


def test_unknown_outside_a_repo_and_without_agents_md(tmp_path, world):
    assert PF.evaluate(tmp_path / "nowhere-but-tmp").status == PF.UNKNOWN
    (world["agent"] / "AGENTS.md").unlink()
    r = PF.evaluate(world["agent"])
    assert r.status == PF.UNKNOWN and "no AGENTS.md in worktree" in r.reason


def test_offline_falls_back_to_last_fetch_and_says_so(world):
    a = world["agent"]
    world["advance"]("2.0.0")
    git(a, "fetch", "-q", "origin")  # last successful fetch already saw 2.0.0
    git(a, "remote", "set-url", "origin", str(world["origin"]) + "-gone")
    r = PF.evaluate(a)
    assert r.status == PF.STALE and r.offline and r.fetch != "fetched"
    assert "offline: compared with origin/main as last fetched" in r.message()
    git(a, "pull", "-q", str(world["origin"]), "main")
    ok = PF.evaluate(a)
    assert ok.status == PF.OK and ok.offline and "offline" in ok.message()


def test_fetch_timeout_is_reported_not_raised(world, monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git fetch", timeout=0.5)

    monkeypatch.setattr(PF.subprocess, "run", boom)
    assert PF.fetch_main(world["agent"], timeout=0.5) == (False, "timed out after 0.5 s")


def test_evaluate_never_raises(monkeypatch, world):
    monkeypatch.setattr(PF, "_evaluate", lambda *a, **k: 1 / 0)
    r = PF.evaluate(world["agent"])
    assert r.status == PF.UNKNOWN and "ZeroDivisionError" in r.reason


# ------------------------------------------------------------------------------------------- revs + CLI


def test_rev_mode_and_worst_of_several(world):
    a = world["agent"]
    old = git(a, "rev-parse", "HEAD")
    world["advance"]("2.0.0")
    git(a, "pull", "-q", "origin", "main")
    new = git(a, "rev-parse", "HEAD")
    rs = PF.evaluate_many(a, [new, old])
    assert [r.status for r in rs] == [PF.OK, PF.STALE] and rs[1].local_source == f"rev:{old}"
    assert PF.worst(rs).status == PF.STALE


def _cli(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(ROOT / "scripts/lib/policy_freshness.py"), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_exit_codes(world, tmp_path):
    ok = _cli(world["agent"], "--gate", "session")
    assert ok.returncode == 0 and "[session] policy OK" in ok.stdout
    world["advance"]("2.0.0")
    stale = _cli(world["agent"], "--json")
    assert stale.returncode == 1 and json.loads(stale.stdout)["status"] == "STALE"
    unknown = _cli(tmp_path)
    assert unknown.returncode == 3 and "UNKNOWN_POLICY" in unknown.stderr


# ------------------------------------------------------------------------------------------- broadcast


class Sender:
    def __init__(self, ok: bool = True):
        self.calls: list[tuple[str, str, str]] = []
        self.ok = ok

    def __call__(self, text, *, identity, kind):
        self.calls.append((text, identity, kind))
        return {"ok": self.ok, "identity": identity}


def _claim(board: B.ClaimBoard, session: str, path: str, version: str | None) -> dict:
    policy = {"policy_version": version, "policy_blob": "a" * 40} if version else None
    return board.claim(vendor="codex", session=session, agent=None, task="t", paths=[path], policy=policy)


def test_broadcast_baseline_then_new_version_marks_and_sends_once(world, tmp_path):
    board = B.ClaimBoard(tmp_path / "claims")
    a1 = _claim(board, "s1", "a", "1.0.0")
    a2 = _claim(board, "s2", "b", None)  # a claim from before claims recorded a version
    s = Sender()
    first = PB.run(world["agent"], apply=True, board=board, sender=s)
    assert first["action"] == "baseline" and s.calls == [] and first["marked"] == []
    assert PB.read_state(PB.state_path(board.dir))["version"] == "1.0.0"

    world["advance"]("2.0.0")
    git(world["agent"], "fetch", "-q", "origin")
    dry = PB.run(world["agent"], apply=False, board=board, sender=s)
    assert dry["action"] == "broadcast" and dry["mode"] == "dry_run" and len(dry["marked"]) == 2
    assert dry["telegram"]["text"] == "AGENTS.md 2.0.0 is live; 2 open claims were on 1.0.0 and have been told"
    assert s.calls == [] and not (board.dir / B.POLICY_CHANGED_DIR).exists()  # a dry run writes and sends nothing

    live = PB.run(world["agent"], apply=True, board=board, sender=s)
    assert live["action"] == "broadcast" and len(s.calls) == 1
    assert s.calls[0][1:] == ("policy-version-live:2.0.0", "policy_version_live")
    for c in (a1, a2):
        assert B.read_policy_mark(board.dir, c["claim_id"])["to_version"] == "2.0.0"
    again = PB.run(world["agent"], apply=True, board=board, sender=s)
    assert again["action"] == "none" and len(s.calls) == 1  # deduplicated per version


def test_broadcast_skips_up_to_date_and_finished_claims(world, tmp_path):
    board = B.ClaimBoard(tmp_path / "claims")
    PB.run(world["agent"], apply=True, board=board, sender=Sender())
    fresh = _claim(board, "s1", "a", "2.0.0")
    done = _claim(board, "s2", "b", "1.0.0")
    board.release(done["claim_id"], session="s2")
    world["advance"]("2.0.0")
    git(world["agent"], "fetch", "-q", "origin")
    s = Sender()
    r = PB.run(world["agent"], apply=True, board=board, sender=s)
    assert (
        r["marked"] == [] and s.calls[0][0] == "AGENTS.md 2.0.0 is live; 0 open claims were on 1.0.0 and have been told"
    )
    assert B.read_policy_mark(board.dir, fresh["claim_id"]) is None


def test_broadcast_retries_an_undelivered_line_a_bounded_number_of_times(world, tmp_path):
    board = B.ClaimBoard(tmp_path / "claims")
    PB.run(world["agent"], apply=True, board=board, sender=Sender())
    world["advance"]("2.0.0")
    git(world["agent"], "fetch", "-q", "origin")
    failing = Sender(ok=False)
    PB.run(world["agent"], apply=True, board=board, sender=failing)
    for _ in range(PB.MAX_TELEGRAM_ATTEMPTS + 3):
        PB.run(world["agent"], apply=True, board=board, sender=failing)
    assert len(failing.calls) == PB.MAX_TELEGRAM_ATTEMPTS
    good = Sender()
    PB.run(world["agent"], apply=True, board=board, sender=good)
    assert good.calls == []  # attempts exhausted: the state says so; nothing re-marks claims


def test_broadcast_unknown_without_origin_main(tmp_path):
    repo = tmp_path / "solo"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    r = PB.run(repo, apply=True, board=B.ClaimBoard(tmp_path / "claims"), sender=Sender())
    assert r["action"] == "unknown" and not (tmp_path / "claims" / PB.STATE_NAME).exists()


def test_status_row_shows_policy_changed_until_heartbeat_records_new_version(world, tmp_path):
    board = B.ClaimBoard(tmp_path / "claims")
    c = _claim(board, "s1", "a", "1.0.0")
    PB.run(world["agent"], apply=True, board=board, sender=Sender())
    world["advance"]("2.0.0")
    git(world["agent"], "fetch", "-q", "origin")
    PB.run(world["agent"], apply=True, board=board, sender=Sender())
    row = next(r for r in board.board()["claims"] if r["claim_id"] == c["claim_id"])
    assert row["policy_changed"]["to_version"] == "2.0.0" and row["policy_version"] == "1.0.0"
    board.heartbeat(c["claim_id"], session="s1", policy={"policy_version": "2.0.0", "policy_blob": "b" * 40})
    row = next(r for r in board.board()["claims"] if r["claim_id"] == c["claim_id"])
    assert row["policy_changed"] is None and row["policy_blob"] == "b" * 40


def test_policy_fields_reject_malformed_blob():
    assert B.policy_fields({"policy_version": "1.0.0", "policy_blob": "not-a-sha"}) == {"policy_version": "1.0.0"}
    assert B.policy_fields(None) == {}
