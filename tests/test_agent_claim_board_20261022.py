"""Agent claim board (operator-approved 2026-10-22): hermetic tests, temp dirs only.

Covers: atomic create under a two-process race, glob overlap, stale takeover, compaction archives then
removes, ``check`` exit codes (incl. the draft-PR fallback and gh unavailable), the read-only API shape,
the warn-only pre-commit script, and the NEVER_SCHEDULED lane row + timer units.
No network: every ``gh`` call is a fake runner or a PATH without gh.
"""

from __future__ import annotations

import json
import multiprocessing as mp
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

T0 = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t = self.t + timedelta(**kw)


def board(tmp_path: Path, clock: Clock | None = None, **kw) -> B.ClaimBoard:
    return B.ClaimBoard(tmp_path / "claims", now=clock or Clock(), **kw)


def mk(b: B.ClaimBoard, session: str, paths, *, vendor="claude", branch=None, task="t"):
    return b.claim(
        vendor=vendor,
        session=session,
        agent=f"{vendor}-agent",
        task=task,
        paths=paths,
        branch=branch or f"feat/{session}",
    )


# ------------------------------------------------------------------------------------------- overlap


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("scripts/x.py", "scripts/x.py", True),
        ("./scripts//x.py", "scripts/x.py", True),
        ("scripts", "scripts/lib/x.py", True),  # directory claims its contents
        ("scripts/lib", "scripts/libx/y.py", False),
        ("scripts/lib/*.py", "scripts/lib/agent_claim_board.py", True),
        ("scripts/lib/*.py", "scripts/lib/sub/x.py", False),  # * stays inside one segment
        ("scripts/**/x.py", "scripts/lib/sub/x.py", True),
        ("scripts/**", "scripts/a/b/c.txt", True),
        ("**/*.md", "docs/ops/AGENT_CLAIM_BOARD.md", True),
        ("docs/*.md", "docs/*.txt", False),  # disjoint suffixes
        ("tests/test_*.py", "tests/*_20261022.py", True),
        ("apps/**/*.tsx", "apps/command-center-v3/src/pages/CoordinationPage.tsx", True),
        ("apps/**/*.tsx", "apps/command-center-v3/src/lib/x.ts", False),
        ("config/lane_registry.json", "config/lane_registry.json.bak", False),
        ("config/lane_?egistry.json", "config/lane_registry.json", True),
        ("config/[lm]ane_registry.json", "config/lane_registry.json", True),
        ("config/[!l]ane_registry.json", "config/lane_registry.json", False),
        ("scripts/*/x.py", "scripts/**", True),
        ("a/b", "c/d", False),
    ],
)
def test_overlap_with_globs(a, b, expected):
    assert B.patterns_overlap(a, b) is expected
    assert B.patterns_overlap(b, a) is expected


@pytest.mark.parametrize("bad", ["/etc/passwd", "../outside", "scripts/../../x", "", "a\x00b"])
def test_paths_outside_the_repo_are_refused(tmp_path, bad):
    with pytest.raises((ValueError, B.ClaimError)):
        mk(board(tmp_path), "s1", [bad])


# ------------------------------------------------------------------------------------------- claim


def test_claim_writes_one_json_per_claim_with_the_operator_fields(tmp_path):
    b = board(tmp_path)
    doc = b.claim(
        vendor="Codex",
        session="s1",
        agent="codex-cloud",
        task="fix x",
        paths=["scripts/x.py", "docs"],
        branch="feat/x",
        pr=17,
        note="n",
    )
    files = sorted((tmp_path / "claims").glob("*.json"))
    assert [f.stem for f in files] == [doc["claim_id"]]
    on_disk = json.loads(files[0].read_text())
    for key in (
        "claim_id",
        "vendor",
        "session",
        "agent",
        "task",
        "paths",
        "branch",
        "pr",
        "started_at",
        "heartbeat_at",
        "status",
        "note",
    ):
        assert key in on_disk
    assert on_disk["vendor"] == "codex" and on_disk["status"] == "active" and on_disk["pr"] == "17"
    assert on_disk["paths"] == ["scripts/x.py", "docs"]
    assert B.valid_claim_id(doc["claim_id"])
    assert not list((tmp_path / "claims").glob(".*.tmp")), "temp files are cleaned up"


def test_overlapping_claim_of_another_session_is_refused_with_holder_branch_since(tmp_path):
    b = board(tmp_path)
    first = mk(b, "s1", ["scripts/lib/*.py"], vendor="cursor", branch="feat/one")
    with pytest.raises(B.ClaimConflict) as ei:
        mk(b, "s2", ["scripts/lib/agent_claim_board.py"], vendor="claude")
    msg = str(ei.value)
    assert first["claim_id"] in msg and "feat/one" in msg and first["started_at"] in msg and "cursor" in msg
    assert len(list((tmp_path / "claims").glob("*.json"))) == 1
    # Disjoint paths and the same session are both fine.
    mk(b, "s2", ["docs/ops/x.md"])
    mk(b, "s1", ["scripts/lib/other.py"])


def test_vendors_are_equal_peers(tmp_path):
    b = board(tmp_path)
    for i, v in enumerate(("claude", "codex", "cursor")):
        mk(b, f"s{i}", [f"area{i}"], vendor=v)
    for i, v in enumerate(("codex", "cursor", "claude")):  # each vendor is refused on another's claim
        with pytest.raises(B.ClaimConflict):
            mk(b, f"other{i}", [f"area{i}/f.py"], vendor=v)


def test_write_exclusive_never_clobbers(tmp_path):
    target = tmp_path / "x.json"
    B._write_exclusive(target, {"a": 1})
    with pytest.raises(FileExistsError):
        B._write_exclusive(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 1}


def _race_create(target: str, payload: int, barrier, q) -> None:
    barrier.wait()
    try:
        B._write_exclusive(Path(target), {"who": payload})
        q.put(("ok", payload))
    except FileExistsError:
        q.put(("exists", payload))


def _race_claim(claims_dir: str, session: str, barrier, q) -> None:
    b = B.ClaimBoard(claims_dir)
    barrier.wait()
    try:
        doc = b.claim(
            vendor="codex",
            session=session,
            agent=None,
            task="race",
            paths=["scripts/lib/shared.py"],
            branch=f"feat/{session}",
        )
        q.put(("ok", session, doc["claim_id"]))
    except B.ClaimConflict:
        q.put(("conflict", session, None))


def test_atomic_create_race_two_processes_same_file(tmp_path):
    ctx = mp.get_context("fork")
    for i in range(10):
        target = tmp_path / f"c{i}.json"
        barrier, q = ctx.Barrier(2), ctx.Queue()
        ps = [ctx.Process(target=_race_create, args=(str(target), n, barrier, q)) for n in (1, 2)]
        for p in ps:
            p.start()
        for p in ps:
            p.join(30)
        results = sorted(q.get(timeout=5)[0] for _ in ps)
        assert results == ["exists", "ok"]
        assert json.loads(target.read_text())["who"] in (1, 2)


def test_atomic_claim_race_two_processes_overlapping_paths(tmp_path):
    ctx = mp.get_context("fork")
    for i in range(6):
        d = tmp_path / f"claims{i}"
        barrier, q = ctx.Barrier(2), ctx.Queue()
        ps = [ctx.Process(target=_race_claim, args=(str(d), s, barrier, q)) for s in ("p1", "p2")]
        for p in ps:
            p.start()
        for p in ps:
            p.join(30)
        results = [q.get(timeout=5) for _ in ps]
        assert sorted(r[0] for r in results) == ["conflict", "ok"], results
        live = [v for v in B.ClaimBoard(d).views()[0] if v.state == "live"]
        assert len(live) == 1


def test_race_fallback_when_flock_is_ignored_later_claimant_withdraws(tmp_path, monkeypatch):
    """A filesystem that ignores flock: a rival appears between our scan and our write. The earlier claim wins."""
    clock = Clock()
    b = board(tmp_path, clock)
    rival_board = board(tmp_path, Clock(T0 - timedelta(seconds=1)))
    real = B._write_exclusive
    injected = {}

    def write_then_rival(target, doc):
        if not injected:
            injected["busy"] = True  # the rival's own write goes straight through
            injected["rival"] = mk(rival_board, "rival", ["scripts/lib/shared.py"], vendor="cursor")
        return real(target, doc)

    monkeypatch.setattr(B, "_write_exclusive", write_then_rival)
    monkeypatch.setattr(B.fcntl, "flock", lambda fd, op: None)  # the filesystem ignores flock
    with pytest.raises(B.ClaimConflict) as ei:
        mk(b, "me", ["scripts/lib/shared.py"])
    assert injected["rival"]["claim_id"] in str(ei.value)
    states = {v.doc["session"]: (v.state, v.doc.get("note")) for v in b.views()[0]}
    assert states["rival"][0] == "live"
    assert states["me"][0] == "abandoned" and "lost race" in states["me"][1]


# ------------------------------------------------------------------------------------------- stale


def test_stale_claim_is_claimable_takeover_recorded_and_old_heartbeat_refused(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    old = mk(b, "s1", ["scripts/x.py"], vendor="codex")
    clock.advance(hours=1, minutes=59)
    with pytest.raises(B.ClaimConflict):
        mk(b, "s2", ["scripts/x.py"])
    clock.advance(minutes=2)  # 2h01m without heartbeat -> stale
    new = mk(b, "s2", ["scripts/x.py"], vendor="claude")
    assert [t["claim_id"] for t in new["takeover_of"]] == [old["claim_id"]]
    v = {x.claim_id: x for x in b.views()[0]}
    assert v[old["claim_id"]].state == "stale" and v[old["claim_id"]].taken_over_by == [new["claim_id"]]
    with pytest.raises(B.ClaimError, match="taken over"):
        b.heartbeat(old["claim_id"], session="s1")


def test_heartbeat_keeps_a_claim_live_and_is_owner_only(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    c = mk(b, "s1", ["docs"])
    clock.advance(hours=1, minutes=50)
    b.heartbeat(c["claim_id"], session="s1", pr="1965", note="pr open")
    clock.advance(hours=1, minutes=50)  # 3h40m since start, 1h50m since heartbeat
    with pytest.raises(B.ClaimConflict):
        mk(b, "s2", ["docs/a.md"])
    with pytest.raises(B.ClaimError, match="belongs to session"):
        b.heartbeat(c["claim_id"], session="s2")
    doc = json.loads(b.claim_path(c["claim_id"]).read_text())
    assert doc["pr"] == "1965" and doc["note"] == "pr open"


def test_release_done_and_abandoned_unblock(tmp_path):
    b = board(tmp_path)
    c1 = mk(b, "s1", ["a"])
    c2 = mk(b, "s1", ["b"])
    b.release(c1["claim_id"], session="s1", status="done")
    b.release(c2["claim_id"], session="s1", status="abandoned", note="gave up")
    mk(b, "s2", ["a", "b"])
    with pytest.raises(B.ClaimError, match="already"):
        b.release(c1["claim_id"], session="s1")
    c3 = mk(b, "s3", ["c"])
    with pytest.raises(B.ClaimError, match="belongs to session"):
        b.release(c3["claim_id"], session="s1")
    forced = b.release(c3["claim_id"], session="op", force=True, released_by="op")
    assert forced["released_by"] == "op"


# ------------------------------------------------------------------------------------------- compact


def test_compact_dry_run_writes_nothing_apply_archives_then_removes(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    done_old = mk(b, "s1", ["a"])
    b.release(done_old["claim_id"], session="s1", status="done")
    stale_old = mk(b, "s2", ["b"])
    clock.advance(days=8)
    live = mk(b, "s3", ["c"])
    done_recent = mk(b, "s4", ["d"])
    b.release(done_recent["claim_id"], session="s4", status="abandoned")
    before = sorted(p.name for p in (tmp_path / "claims").iterdir())

    dry = b.compact(apply=False)
    assert dry["mode"] == "dry_run" and dry["eligible"] == 2 and dry["removed"] == 0
    assert {i["claim_id"] for i in dry["items"]} == {done_old["claim_id"], stale_old["claim_id"]}
    assert sorted(p.name for p in (tmp_path / "claims").iterdir()) == before
    assert not b.history.exists()

    res = b.compact(apply=True)
    assert (res["archived"], res["removed"], res["skipped"]) == (2, 2, [])
    lines = [json.loads(x) for x in b.history.read_text().splitlines()]
    assert {r["claim"]["claim_id"] for r in lines} == {done_old["claim_id"], stale_old["claim_id"]}
    assert all(r["schema"] == "AgentClaimArchive@v1" and len(r["sha256"]) == 64 for r in lines)
    assert {r["state_at_archive"] for r in lines} == {"done", "stale"}
    remaining = {p.stem for p in (tmp_path / "claims").glob("*.json")}
    assert remaining == {live["claim_id"], done_recent["claim_id"]}
    # The archived path trips loudly instead of reading as "never existed".
    with pytest.raises(B.ClaimError, match="compacted into"):
        b.heartbeat(done_old["claim_id"], session="s1")
    # Idempotent and append-only.
    again = b.compact(apply=True)
    assert again["eligible"] == 0
    assert len(b.history.read_text().splitlines()) == 2


def test_compact_keeps_the_file_when_the_archive_cannot_be_read_back(tmp_path, monkeypatch):
    clock = Clock()
    b = board(tmp_path, clock)
    c = mk(b, "s1", ["a"])
    b.release(c["claim_id"], session="s1")
    clock.advance(days=8)
    monkeypatch.setattr(B.ClaimBoard, "_history_has", lambda self, cid, dg: False)
    res = b.compact(apply=True)
    assert res["removed"] == 0 and res["skipped"][0]["reason"] == "archive_not_readable"
    assert b.claim_path(c["claim_id"]).exists()


# ------------------------------------------------------------------------------------------- check / CLI


def run_cli(tmp_path, *args, env_session=None):
    argv = ["--claims-dir", str(tmp_path / "claims"), *args]
    return CLI.main(argv)


def test_cli_check_exit_codes(tmp_path, capsys):
    assert (
        run_cli(
            tmp_path,
            "--vendor",
            "codex",
            "--session",
            "s1",
            "claim",
            "--task",
            "t",
            "--paths",
            "scripts/lib/**",
            "--branch",
            "feat/one",
        )
        == 0
    )
    assert (
        run_cli(tmp_path, "--session", "s2", "check", "--no-gh", "--exclude-branch", "feat/two", "--paths", "docs/x.md")
        == 0
    )
    assert (
        run_cli(
            tmp_path,
            "--session",
            "s2",
            "check",
            "--no-gh",
            "--exclude-branch",
            "feat/two",
            "--paths",
            "scripts/lib/a/b.py",
        )
        == 1
    )
    err = capsys.readouterr().err
    assert "CONFLICT" in err and "feat/one" in err and "codex" in err
    # warn-only (pre-commit mode): same report, exit 0
    assert (
        run_cli(
            tmp_path,
            "--session",
            "s2",
            "check",
            "--no-gh",
            "--warn-only",
            "--exclude-branch",
            "feat/two",
            "--paths",
            "scripts/lib/a/b.py",
        )
        == 0
    )
    assert "WARN" in capsys.readouterr().err
    # own claims (same branch, or same session) never conflict
    assert (
        run_cli(
            tmp_path,
            "--session",
            "zz",
            "check",
            "--no-gh",
            "--exclude-branch",
            "feat/one",
            "--paths",
            "scripts/lib/a/b.py",
        )
        == 0
    )
    assert (
        run_cli(
            tmp_path,
            "--session",
            "s1",
            "check",
            "--no-gh",
            "--exclude-branch",
            "other",
            "--paths",
            "scripts/lib/a/b.py",
        )
        == 0
    )
    # usage error
    assert run_cli(tmp_path, "--session", "s2", "check", "--no-gh", "--exclude-branch", "x", "--paths", "../etc") == 2
    # refused claim exits 1
    assert (
        run_cli(
            tmp_path, "--session", "s2", "claim", "--task", "t", "--paths", "scripts/lib/x.py", "--branch", "feat/two"
        )
        == 1
    )


def test_cli_check_json_and_list(tmp_path, capsys):
    run_cli(tmp_path, "--vendor", "cursor", "--session", "s1", "claim", "--task", "t", "--paths", "a", "--branch", "b1")
    capsys.readouterr()
    assert (
        run_cli(tmp_path, "--session", "s2", "check", "--no-gh", "--json", "--exclude-branch", "b2", "--paths", "a/x")
        == 1
    )
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "AgentClaimCheck@v1" and out["conflict"] is True
    assert out["conflicts"][0]["source"] == "claim" and out["draft_prs_consulted"] is False
    assert run_cli(tmp_path, "list") == 0
    assert "cursor" in capsys.readouterr().out
    assert run_cli(tmp_path, "list", "--json") == 0
    assert json.loads(capsys.readouterr().out)["counts"]["live"] == 1


def _gh(stdout="[]", rc=0, stderr=""):
    def runner(cmd, **kw):
        assert cmd[:4] == ["gh", "pr", "list", "--draft"] and "files" in cmd[-1]
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr=stderr)

    return runner


def test_draft_pr_fallback_finds_cloud_agent_work():
    prs = [
        {
            "number": 1970,
            "headRefName": "codex/cloud-fix",
            "title": "cloud",
            "author": {"login": "codex"},
            "url": "https://example.invalid/pr/1970",
            "files": [{"path": "scripts/lib/x.py"}, {"path": "README.md"}],
        },
        {"number": 1971, "headRefName": "feat/mine", "files": [{"path": "scripts/lib/x.py"}]},
        {"number": 1972, "headRefName": "other", "files": [{"path": "docs/y.md"}]},
    ]
    rows, warn = B.draft_pr_conflicts(["scripts/lib/*.py"], exclude_branch="feat/mine", runner=_gh(json.dumps(prs)))
    assert warn is None
    assert [r["pr"] for r in rows] == [1970] and rows[0]["source"] == "draft_pr"
    assert rows[0]["overlaps"] == [{"path": "scripts/lib/*.py", "held": "scripts/lib/x.py"}]


@pytest.mark.parametrize(
    "runner,needle",
    [
        (_gh(rc=1, stderr="gh auth login required"), "exited 1"),
        (_gh(stdout="not json"), "unparseable"),
    ],
)
def test_draft_pr_fallback_degrades_to_a_warning(runner, needle):
    rows, warn = B.draft_pr_conflicts(["a"], runner=runner)
    assert rows == [] and needle in warn and "not consulted" in warn


def test_draft_pr_fallback_gh_missing_or_slow():
    def missing(cmd, **kw):
        raise FileNotFoundError("gh")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    assert "not installed" in B.draft_pr_conflicts(["a"], runner=missing)[1]
    assert "timed out" in B.draft_pr_conflicts(["a"], runner=slow)[1]


def test_cli_check_without_gh_on_path_warns_and_does_not_fail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    assert run_cli(tmp_path, "--session", "s", "check", "--exclude-branch", "b", "--paths", "x") == 0
    assert "WARN: gh not installed" in capsys.readouterr().err


def test_cli_check_draft_pr_conflict_exits_1(tmp_path, monkeypatch, capsys):
    prs = [{"number": 9, "headRefName": "cursor/bg", "files": [{"path": "docs/x.md"}]}]
    monkeypatch.setattr(B.subprocess, "run", _gh(json.dumps(prs)))
    assert run_cli(tmp_path, "--session", "s", "check", "--exclude-branch", "b", "--paths", "docs") == 1
    assert "draft PR #9" in capsys.readouterr().err


# ------------------------------------------------------------------------------------------- hook script


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"},
    )


def test_precommit_script_is_warn_only(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts" / "lib").mkdir(parents=True)
    for rel in (
        "scripts/agent_claim.py",
        "scripts/agent_claim_precommit.sh",
        "scripts/lib/agent_claim_board.py",
        "scripts/lib/agent_claim_lifecycle.py",
        "scripts/lib/agent_claim_worklog.py",
        "scripts/lib/agent_task_board.py",
        "scripts/lib/agent_file_lease.py",
        "scripts/lib/persistent_state_root.py",
    ):
        (repo / rel).write_bytes((ROOT / rel).read_bytes())
    (repo / "scripts" / "__init__.py").write_text("")
    (repo / "scripts" / "lib" / "__init__.py").write_text("")
    _git(repo, "init", "-q", "-b", "feat/mine")
    claims = tmp_path / "claims"
    B.ClaimBoard(claims).claim(
        vendor="codex", session="other", agent=None, task="t", paths=["docs"], branch="feat/theirs"
    )
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("x")
    _git(repo, "add", "docs/a.md")
    env = {**os.environ, "TRADEAI_AGENT_CLAIMS_DIR": str(claims), "AGENT_CLAIM_NO_GH": "1", "AGENT_CLAIM_SESSION": "me"}
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "agent_claim_precommit.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0
    assert "WARN: docs/a.md" in proc.stderr and "feat/theirs" in proc.stderr and "warn-only" in proc.stderr


def test_hooks_framework_left_untouched_operator_surface():
    """.githooks/ is operator-only (AGENTS.md §23.13 exclusion); the script ships with an install note instead."""
    hook = (ROOT / ".githooks" / "pre-commit").read_text()
    assert "agent_claim" not in hook
    script = (ROOT / "scripts" / "agent_claim_precommit.sh").read_text()
    # 2026-10-23: policy-gated (warn below AGENTS.md 20.0.0 ACTIVE, block from it); the install line keeps the rc
    assert 'bash "$ROOT/scripts/agent_claim_precommit.sh" || exit 1' in script and "exit 0" in script


# ------------------------------------------------------------------------------------------- API


def test_board_view_shape(tmp_path, monkeypatch):
    clock = Clock()
    b = board(tmp_path, clock)
    a = mk(b, "s1", ["a"], vendor="codex")
    s = mk(b, "s2", ["b"], vendor="cursor")
    clock.advance(hours=3)
    b.heartbeat(a["claim_id"], session="s1")
    d = mk(b, "s3", ["c"])
    b.release(d["claim_id"], session="s3")
    view = b.board()
    assert view["schema"] == "AgentClaimBoard@v1" and view["dir_present"] is True
    assert view["counts"] == {"live": 1, "stale": 1, "done": 1, "abandoned": 0}
    assert [r["state"] for r in view["claims"]] == ["live", "stale", "done"]
    row = view["claims"][0]
    assert set(row) >= {
        "claim_id",
        "state",
        "vendor",
        "session",
        "agent",
        "task",
        "paths",
        "branch",
        "pr",
        "started_at",
        "heartbeat_at",
        "heartbeat_age_minutes",
        "note",
        "taken_over_by",
    }
    assert [r["claim_id"] for r in b.board(include_finished=False)["claims"]] == [a["claim_id"], s["claim_id"]]


def test_api_route_get_only_and_never_creates_the_dir(tmp_path, monkeypatch):
    import api_v2

    missing = tmp_path / "nothing-here"
    monkeypatch.setenv("TRADEAI_AGENT_CLAIMS_DIR", str(missing))
    status, body = api_v2.handle("/api/v2/coordination/claims", method="GET", body=None, query={})
    assert status == 200 and body["ok"] is True
    assert body["data"]["schema"] == "AgentClaimBoard@v1" and body["data"]["dir_present"] is False
    assert body["data"]["claims"] == [] and not missing.exists()
    assert api_v2.handle("/api/v2/coordination/claims", method="POST", body={}, query={}) == (
        405,
        {"ok": False, "error": "read_only"},
    )

    claims = tmp_path / "claims"
    monkeypatch.setenv("TRADEAI_AGENT_CLAIMS_DIR", str(claims))
    c = B.ClaimBoard(claims).claim(vendor="claude", session="s", agent=None, task="t", paths=["x"], branch="b")
    B.ClaimBoard(claims).release(c["claim_id"], session="s")
    s2, all_rows = api_v2.handle("/api/v2/coordination/claims", method="GET", body=None, query={})
    s3, active = api_v2.handle("/api/v2/coordination/claims", method="GET", body=None, query={"active": ["1"]})
    assert len(all_rows["data"]["claims"]) == 1 and active["data"]["claims"] == []


def test_cc_panel_wired_with_tooltips():
    page = (ROOT / "apps/command-center-v3/src/pages/CoordinationPage.tsx").read_text()
    assert "import AgentClaimsPanel from './AgentClaimsPanel'" in page and 'agents: "Who\'s working"' in page
    assert "today: 'n8n today'" in page  # the n8n-today test's anchor survives
    comp = (ROOT / "apps/command-center-v3/src/pages/AgentClaimsPanel.tsx").read_text()
    assert "/api/v2/coordination/claims" in comp and "designTokens" in comp
    assert comp.count("title=") >= 8, "every chip / header / cell carries a tooltip"


# ------------------------------------------------------------------------------------------- scheduling


def test_lane_row_never_scheduled_and_units_in_repo():
    reg = json.loads((ROOT / "config" / "lane_registry.json").read_text())
    row = next(r for r in reg["lanes"] if r["lane_id"] == "agent-claim-compact")
    assert row["state"] == "NEVER_SCHEDULED"
    assert row["scheduler"] == {
        "kind": "systemd",
        "expression": "tradeai-agent-claim-compact.timer",
        "match": "scripts/agent_claim.py compact",
    }
    assert row["output_signal"] == {
        "kind": "json_key",
        "path": "data/runtime/agent-claim-compact_last.json",
        "key": "ok_at",
    }
    unit = (ROOT / "linux_launchers/systemd/tradeai-agent-claim-compact.service").read_text()
    timer = (ROOT / "linux_launchers/systemd/tradeai-agent-claim-compact.timer").read_text()
    assert "scripts/agent_claim.py compact --apply --lane-receipt" in unit and "Type=oneshot" in unit
    assert "OnCalendar=Sun" in timer and "WantedBy=timers.target" in timer
    assert CLI.LANE_ID == row["lane_id"]


def test_compact_lane_receipt_only_on_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_STATE_ROOT", str(tmp_path / "state"))
    receipt = tmp_path / "state" / "data" / "runtime" / "agent-claim-compact_last.json"
    assert run_cli(tmp_path, "compact", "--dry-run") == 0
    assert not receipt.exists()
    assert run_cli(tmp_path, "compact", "--apply", "--lane-receipt") == 0
    doc = json.loads(receipt.read_text())
    assert doc["lane_id"] == "agent-claim-compact" and doc.get("ok_at")
