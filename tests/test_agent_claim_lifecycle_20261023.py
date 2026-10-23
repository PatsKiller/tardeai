"""Agent claim board lifecycle + policy-gated pre-commit (operator 2026-10-23): hermetic, temp dirs only.

Stages claimed -> building -> pr_open -> ci_green -> merged -> released | abandoned. Covers declared stage
transitions, auto-advance from a FAKE gh (PR state, required checks of the head SHA), file locks released at
merge, released detection from FAKE release receipts (apply receipt / served SHA, fake ancestry), degradation
when gh is missing / slow / failing, compaction holding PR work until release, the read-only API projection
(never writes), and the pre-commit gate: warn below AGENTS.md 20.0.0 ACTIVE, block from it (holder, branch,
since printed; no own claim = block), TRADEAI_CLAIM_OVERRIDE logged to the history.
No network: every gh call goes to a fake runner; git ancestry is a fake callable.
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

T0 = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
HEAD = "a" * 40
MERGE = "b" * 40
SERVED = "c" * 40
REPO = "Owner/repo"
REQUIRED = ["ci-gate", "cio-hardening"]


class Clock:
    def __init__(self, t: datetime = T0):
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t = self.t + timedelta(**kw)


class FakeGH:
    """Answers ``gh api --method GET <path>`` from a dict; records every command."""

    def __init__(self, routes: dict | None = None, *, exc: BaseException | None = None, rc: int = 0, stderr: str = ""):
        self.routes = routes or {}
        self.exc = exc
        self.rc = rc
        self.stderr = stderr
        self.cmds: list[list[str]] = []

    def __call__(self, cmd, **kw):
        if cmd[:4] == ["gh", "pr", "list", "--draft"]:  # the 10-22 draft-PR fallback of `check`
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        self.cmds.append(list(cmd))
        assert cmd[:4] == ["gh", "api", "--method", "GET"], cmd
        assert kw.get("timeout"), "every gh call carries a timeout"
        if self.exc is not None:
            raise self.exc
        if self.rc:
            return subprocess.CompletedProcess(cmd, self.rc, stdout="", stderr=self.stderr)
        path = cmd[4]
        for key, val in self.routes.items():
            if path.startswith(key):
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(val), stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="gh: Not Found (HTTP 404)")


def pr_doc(number=7, *, state="open", merged=False, branch="feat/a", created="2026-10-23T14:05:00Z"):
    return {
        "number": number,
        "state": "closed" if merged or state == "closed" else "open",
        "merged_at": "2026-10-23T16:00:00Z" if merged else None,
        "merge_commit_sha": MERGE if merged else "d" * 40,
        "closed_at": "2026-10-23T16:00:00Z" if merged or state == "closed" else None,
        "created_at": created,
        "html_url": f"https://github.com/{REPO}/pull/{number}",
        "draft": False,
        "title": "feat: thing",
        "base": {"ref": "main"},
        "head": {"sha": HEAD, "ref": branch},
    }


def runs(**conclusions):
    out = []
    for i, (name, concl) in enumerate(conclusions.items()):
        name = name.replace("_", "-")
        if concl == "pending":
            out.append(
                {
                    "id": i,
                    "name": name,
                    "status": "in_progress",
                    "conclusion": None,
                    "started_at": "2026-10-23T14:10:00Z",
                }
            )
        else:
            out.append(
                {
                    "id": i,
                    "name": name,
                    "status": "completed",
                    "conclusion": concl,
                    "started_at": "2026-10-23T14:10:00Z",
                    "completed_at": "2026-10-23T14:30:00Z",
                }
            )
    return {"total_count": len(out), "check_runs": out}


def routes(pr, checks=None, required=REQUIRED):
    r = {
        f"repos/{REPO}/pulls/{pr['number']}": pr,
        f"repos/{REPO}/pulls?head=": [pr],
        f"repos/{REPO}/branches/main/protection/required_status_checks": {"contexts": required},
    }
    if checks is not None:
        r[f"repos/{REPO}/commits/{HEAD}/check-runs"] = checks
    return r


class FakeRelease(LC.ReleaseReader):
    def __init__(self, tmp: Path, *, served: str | None = None, receipts=(), ancestors=()):
        tmp.mkdir(parents=True, exist_ok=True)
        pins = tmp / "deploy" / "release_pins"
        pins.mkdir(parents=True, exist_ok=True)
        for name, sha, at in receipts:
            rel = tmp / "releases" / f"{sha[:9]}-main-exact"
            rel.mkdir(parents=True, exist_ok=True)
            (rel / "BUILD_SHA").write_text(sha + "\n")
            (pins / name).write_text(
                json.dumps({"schema": "ReleasePinReceipt@v1", "mode": "apply", "at": at, "target_release": str(rel)})
            )
        anc = set(ancestors)
        super().__init__(
            tmp / "releases",
            tmp / "deploy",
            is_ancestor=lambda a, b: (a, b) in anc,
            serving=lambda: {"sha": served, "since": "2026-10-24T13:00:00Z"},
        )


def observer(gh=None, rel=None, clock=None):
    return LC.LifecycleObserver(LC.GitHubReader(REPO, runner=gh) if gh is not None else None, rel, now=clock or Clock())


def board(tmp_path: Path, clock: Clock | None = None, obs=None) -> B.ClaimBoard:
    return B.ClaimBoard(tmp_path / "claims", now=clock or Clock(), observer=obs)


def mk(b, session, paths, *, branch=None, pr=None):
    return b.claim(
        vendor="claude",
        session=session,
        agent=f"{session}-agent",
        task="t",
        paths=paths,
        branch=branch or f"feat/{session}",
        pr=pr,
    )


def mkw(b, session, paths, *, branch=None, pr=None, plan=("step one",)):
    """A claim with a worklog and a plan, as `agent_claim.py claim --plan ...` makes it."""
    d = mk(b, session, paths, branch=branch, pr=pr)
    b.worklog(d["claim_id"]).create(d, plan=list(plan))
    return d


def view(b, cid):
    return next(v for v in b.views()[0] if v.claim_id == cid)


# ------------------------------------------------------------------------------------------- declared stages


def test_new_claim_is_claimed_with_timestamp(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"])
    v = view(b, d["claim_id"])
    assert v.stage == "claimed" and v.lifecycle["stages"] == {"claimed": "2026-10-23T14:00:00Z"}
    assert v.lifecycle["locks_held"] is True and v.blocking


def test_declare_building_then_pr_open(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mk(b, "s1", ["docs/a.md"])
    clock.advance(minutes=10)
    b.stage(d["claim_id"], "building", session="s1")
    assert view(b, d["claim_id"]).stage == "building"
    with pytest.raises(B.ClaimError, match="needs --pr"):
        b.stage(d["claim_id"], "pr_open", session="s1")
    clock.advance(minutes=20)
    doc = b.stage(d["claim_id"], "pr_open", session="s1", pr="1990")
    assert doc["pr"] == "1990" and doc["heartbeat_at"] == "2026-10-23T14:30:00Z"
    v = view(b, d["claim_id"])
    assert v.stage == "pr_open"
    assert v.lifecycle["stages"]["building"] == "2026-10-23T14:10:00Z"
    assert v.lifecycle["stages"]["pr_open"] == "2026-10-23T14:30:00Z"
    assert v.blocking  # an open PR still holds its files


@pytest.mark.parametrize("stage", ["ci_green", "merged", "released", "claimed", "abandoned"])
def test_evidence_stages_cannot_be_declared(tmp_path, stage):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"])
    with pytest.raises(B.ClaimError, match="cannot be declared"):
        b.stage(d["claim_id"], stage, session="s1")


def test_stage_is_owner_only_and_refused_after_release(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"])
    with pytest.raises(B.ClaimError, match="belongs to session"):
        b.stage(d["claim_id"], "building", session="s2")
    b.release(d["claim_id"], session="s1", status="abandoned")
    with pytest.raises(B.ClaimError, match="abandoned"):
        b.stage(d["claim_id"], "building", session="s1")
    assert view(b, d["claim_id"]).stage == "abandoned"


def test_legacy_claim_without_stages_reads_as_claimed_or_pr_open(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"])
    p = b.claim_path(d["claim_id"])
    doc = json.loads(p.read_text())
    doc.pop("stages", None)
    doc["pr"] = "55"
    p.write_text(json.dumps(doc))
    v = view(b, d["claim_id"])
    assert v.stage == "pr_open" and v.lifecycle["pr_number"] == 55


def test_cli_stage_command(tmp_path, capsys):
    argv = ["--claims-dir", str(tmp_path / "claims"), "--session", "s1", "--vendor", "codex"]
    assert CLI.main([*argv, "claim", "--task", "t", "--paths", "docs/a.md", "--branch", "feat/x"]) == 0
    cid = capsys.readouterr().out.strip()
    assert CLI.main([*argv, "stage", cid, "building"]) == 0
    assert CLI.main([*argv, "stage", cid, "pr_open"]) == 2  # no PR
    assert CLI.main([*argv, "stage", cid, "pr_open", "--pr", "12"]) == 0
    with pytest.raises(SystemExit):
        CLI.main([*argv, "stage", cid, "merged"])  # not a declarable choice


# ------------------------------------------------------------------------------------------- auto-advance (fake gh)


def test_ci_from_runs_required_latest_wins_and_missing_is_pending():
    r = runs(ci_gate="success", cio_hardening="success")["check_runs"]
    assert LC.ci_from_runs(r, REQUIRED)["state"] == "green"
    rerun = dict(r[0], id=99, started_at="2026-10-23T15:00:00Z", conclusion="failure")
    assert LC.ci_from_runs(r + [rerun], REQUIRED)["failing"] == ["ci-gate"]
    assert LC.ci_from_runs(r[:1], REQUIRED)["pending"] == ["cio-hardening"]
    assert LC.ci_from_runs(None, REQUIRED)["state"] == "unknown"
    assert LC.ci_from_runs(r, None)["basis"] == "all_checks"


def test_auto_advance_pr_open_to_ci_green(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    gh = FakeGH(routes(pr_doc(), runs(ci_gate="success", cio_hardening="pending")))
    b.observer = observer(gh)
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.stage == "pr_open" and v.lifecycle["ci"]["state"] == "pending"
    assert v.lifecycle["stages"]["pr_open"] == "2026-10-23T14:05:00Z"  # PR created_at, from GitHub
    gh.routes = routes(pr_doc(), runs(ci_gate="success", cio_hardening="success"))
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.stage == "ci_green" and v.lifecycle["stages"]["ci_green"] == "2026-10-23T14:30:00Z"
    assert v.blocking  # green CI is not merged: files still held
    assert (tmp_path / "claims" / "lifecycle" / f"{d['claim_id']}.json").is_file()
    assert all(c[:4] == ["gh", "api", "--method", "GET"] for c in gh.cmds)


def test_failing_ci_is_a_card_warning_and_new_push_regresses_current_stage(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    b.observer = observer(FakeGH(routes(pr_doc(), runs(ci_gate="success", cio_hardening="success"))))
    b.refresh_claims()
    b.observer = observer(FakeGH(routes(pr_doc(), runs(ci_gate="failure", cio_hardening="success"))))
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.stage == "pr_open" and "ci_green" in v.lifecycle["stages"]  # history kept, current regressed
    row = B.public_row(v, T0)
    assert row["stale_warning"].startswith("CI failing: ci-gate")


def test_pr_found_by_branch_when_agent_never_declared_it(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], branch="feat/a")
    b.observer = observer(FakeGH(routes(pr_doc(9), runs(ci_gate="success", cio_hardening="success"))))
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.lifecycle["pr_number"] == 9 and v.stage == "ci_green"
    assert v.lifecycle["pr_url"].endswith("/pull/9")


def test_merge_releases_file_locks_but_keeps_card(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    with pytest.raises(B.ClaimConflict):
        mk(b, "s2", ["docs/a.md"])
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))))
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.stage == "merged" and v.lifecycle["stages"]["merged"] == "2026-10-23T16:00:00Z"
    assert not v.blocking and v.state == "live"
    b2 = board(tmp_path, clock)
    assert b2.conflicts(["docs/a.md"], session="s2") == []
    mk(b2, "s2", ["docs/a.md"])  # files are free
    rows = b2.board(include_finished=False)["claims"]
    assert d["claim_id"] in {r["claim_id"] for r in rows}  # still on the board until released
    assert next(r for r in rows if r["claim_id"] == d["claim_id"])["locks_held"] is False


def test_claim_refreshes_a_conflicting_holder_and_finds_it_merged(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    gh = FakeGH(routes(pr_doc(merged=True)))
    b2 = board(tmp_path, obs=observer(gh))
    mk(b2, "s2", ["docs/a.md"])  # would conflict, but the holder's PR merged
    assert any("pulls/7" in c[4] for c in gh.cmds)
    side = json.loads((tmp_path / "claims" / "lifecycle" / f"{d['claim_id']}.json").read_text())
    assert side["pr_state"] == "merged" and side["merge_sha"] == MERGE


def test_cli_check_clears_after_merge(tmp_path, monkeypatch, capsys):
    b = board(tmp_path)
    mk(b, "s1", ["docs/a.md"], pr="7")
    fake = FakeGH(routes(pr_doc(merged=True)))
    monkeypatch.setattr(LC, "default_repo", lambda root=None: REPO)
    monkeypatch.setattr(LC.subprocess, "run", fake)
    monkeypatch.setattr(LC.ReleaseReader, "serving", lambda self: {"sha": None})
    rc = CLI.main(
        [
            "--claims-dir",
            str(tmp_path / "claims"),
            "--session",
            "s2",
            "check",
            "--no-gh",
            "--exclude-branch",
            "x",
            "--paths",
            "docs/a.md",
        ]
    )
    assert rc == 1  # --no-gh: GitHub not consulted, the holder still blocks (fail safe)
    rc = CLI.main(
        [
            "--claims-dir",
            str(tmp_path / "claims"),
            "--session",
            "s2",
            "check",
            "--exclude-branch",
            "x",
            "--paths",
            "docs/a.md",
        ]
    )
    out = capsys.readouterr()
    assert rc == 0 and "clear" in out.out


# ------------------------------------------------------------------------------------------- released detection


def test_released_when_merge_is_ancestor_of_an_apply_receipt(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    rel = FakeRelease(
        tmp_path / "rel",
        served=SERVED,
        receipts=[
            ("apply-20261023T120000Z.json", "e" * 40, "2026-10-23T12:00:00+00:00"),  # before the merge
            ("apply-20261024T120000Z.json", SERVED, "2026-10-24T12:00:00+00:00"),
        ],
        ancestors=[(MERGE, SERVED), (MERGE, "e" * 40)],
    )
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))), rel)
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.stage == "released"
    assert v.lifecycle["stages"]["released"] == "2026-10-24T12:00:00Z"  # the receipt before the merge is skipped
    assert v.lifecycle["released"]["basis"] == "release_pins/apply-20261024T120000Z.json"


def test_released_from_served_sha_when_no_receipt_contains_it(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    rel = FakeRelease(tmp_path / "rel", served=SERVED, ancestors=[(MERGE, SERVED)])
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))), rel)
    b.refresh_claims()
    v = view(b, d["claim_id"])
    assert v.stage == "released" and v.lifecycle["released"]["basis"] == "served CURRENT/BUILD_SHA"


def test_merged_not_yet_served_stays_merged_and_warns_after_days(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    rel = FakeRelease(tmp_path / "rel", served=SERVED, ancestors=[])
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))), rel)
    b.refresh_claims()
    assert view(b, d["claim_id"]).stage == "merged"
    clock.advance(days=5)
    row = B.public_row(view(b, d["claim_id"]), clock())
    assert "not live yet" in row["stale_warning"]


def test_released_without_github_uses_cached_merge_sha(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))))
    b.refresh_claims()
    gh_down = FakeGH(exc=FileNotFoundError("gh"))
    rel = FakeRelease(tmp_path / "rel", served=SERVED, ancestors=[(MERGE, SERVED)])
    b.observer = observer(gh_down, rel)
    b.refresh_claims()
    assert view(b, d["claim_id"]).stage == "released"
    assert gh_down.cmds == []  # a known merge never asks GitHub again


# ------------------------------------------------------------------------------------------- degradation


@pytest.mark.parametrize(
    "fake,needle",
    [
        (FakeGH(exc=FileNotFoundError("gh")), "gh not installed"),
        (FakeGH(exc=subprocess.TimeoutExpired("gh", 8)), "timed out"),
        (FakeGH(rc=4, stderr="gh auth login required"), "gh exited 4"),
    ],
)
def test_gh_unavailable_degrades_to_declared_stage_and_keeps_blocking(tmp_path, fake, needle):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"])
    b.stage(d["claim_id"], "pr_open", session="s1", pr="7")
    b.observer = observer(fake)
    got = b.refresh_claims()
    assert needle in (b.last_observe_warning or "")
    v = view(b, d["claim_id"])
    assert v.stage == "pr_open" and v.blocking
    assert any(needle in w for w in got[d["claim_id"]]["warnings"])
    with pytest.raises(B.ClaimConflict):
        board(tmp_path, obs=observer(fake)).claim(vendor="x", session="s2", agent=None, task="t", paths=["docs/a.md"])


def test_gh_down_stops_after_first_failure(tmp_path):
    b = board(tmp_path)
    for i in range(3):
        mk(b, f"s{i}", [f"docs/{i}.md"], pr=str(10 + i))
    fake = FakeGH(exc=subprocess.TimeoutExpired("gh", 8))
    b.observer = observer(fake)
    b.refresh_claims()
    assert len(fake.cmds) == 1  # one timeout, not one per claim


def test_github_reader_refuses_non_repo_paths():
    r = LC.GitHubReader(REPO, runner=FakeGH())
    val, warn = r.get("graphql")
    assert val is None and "refused" in warn
    assert r.calls == []


# ------------------------------------------------------------------------------------------- sync + compaction


def test_sync_dry_run_writes_nothing_apply_writes(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))))
    res = b.sync(apply=False)
    assert res["mode"] == "dry_run" and res["changes"][0]["to"] == "merged" and res["changes"][0]["locks_released"]
    assert not (tmp_path / "claims" / "lifecycle").exists()
    b2 = board(tmp_path, obs=observer(FakeGH(routes(pr_doc(merged=True)))))
    res = b2.sync(apply=True)
    assert res["written"] == [d["claim_id"]]
    assert board(tmp_path).views()[0][0].stage == "merged"  # persisted


def test_compaction_holds_pr_work_until_released_then_archives_with_lifecycle(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    b.release(d["claim_id"], session="s1", status="done")
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))), FakeRelease(tmp_path / "rel", served=None), clock)
    b.refresh_claims()
    clock.advance(days=10)
    assert b.compact_plan() == []  # merged, not live: held on the board
    b.observer = observer(None, FakeRelease(tmp_path / "rel2", served=SERVED, ancestors=[(MERGE, SERVED)]), clock)
    res = b.compact(apply=True)  # syncs first: released 2026-10-24T13:00Z, 9 days before now (> 7)
    assert res["removed"] == 1
    line = json.loads((tmp_path / "claims" / B.HISTORY_NAME).read_text().splitlines()[-1])
    assert line["claim"]["claim_id"] == d["claim_id"] and line["lifecycle"]["released"]["sha"] == SERVED
    assert line["stage_at_archive"] == "released"
    assert not (tmp_path / "claims" / "lifecycle" / f"{d['claim_id']}.json").exists()


def test_compaction_hold_has_a_ceiling(tmp_path):
    clock = Clock()
    b = board(tmp_path, clock)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    clock.advance(days=B.HOLD_MAX_DAYS - 1)
    assert b.compact_plan() == []
    clock.advance(days=2)
    assert [p["claim_id"] for p in b.compact_plan()] == [d["claim_id"]]


# ------------------------------------------------------------------------------------------- API projection


def test_board_view_is_read_only_and_carries_lifecycle(tmp_path):
    b = board(tmp_path)
    d = mk(b, "s1", ["docs/a.md"], pr="7")
    fake = FakeGH(routes(pr_doc(), runs(ci_gate="success", cio_hardening="success")))
    cache = LC.CachedObserver(lambda: observer(fake))
    before = sorted(p.name for p in (tmp_path / "claims").rglob("*"))
    out = B.board_view(tmp_path / "claims", observer=cache, background=False)
    assert sorted(p.name for p in (tmp_path / "claims").rglob("*")) == before  # nothing written
    row = out["claims"][0]
    assert row["claim_id"] == d["claim_id"] and row["stage"] == "ci_green" and row["ci"]["state"] == "green"
    assert row["pr_url"].endswith("/pull/7") and row["locks_held"] is True and row["age_minutes"] is not None
    assert out["stages"] == list(LC.ALL_STAGES) and out["stage_counts"]["ci_green"] == 1
    assert set(out["stage_help"]) == set(LC.ALL_STAGES)
    for key in ("counts", "claims_dir", "stale_after_hours", "unreadable", "truncated"):
        assert key in out  # additive: the 10-22 shape is intact
    n = len(fake.cmds)
    B.board_view(tmp_path / "claims", observer=cache, background=False)
    assert len(fake.cmds) == n  # cached inside the TTL


def test_board_view_degrades_when_gh_missing(tmp_path):
    b = board(tmp_path)
    mk(b, "s1", ["docs/a.md"], pr="7")
    cache = LC.CachedObserver(lambda: observer(FakeGH(exc=FileNotFoundError("gh"))))
    out = B.board_view(tmp_path / "claims", observer=cache, background=False)
    assert "gh not installed" in out["lifecycle"]["warning"]
    assert out["claims"][0]["stage"] == "pr_open"


def test_board_view_missing_dir_creates_nothing(tmp_path):
    cache = LC.CachedObserver(lambda: observer(FakeGH()))
    out = B.board_view(tmp_path / "nope", observer=cache, background=False)
    assert out["dir_present"] is False and out["claims"] == []
    assert not (tmp_path / "nope").exists()


# ------------------------------------------------------------------------------------------- pre-commit gate


def agents_md(tmp_path: Path, version: str, status: str = "ACTIVE", row_status: str | None = None) -> Path:
    p = tmp_path / f"AGENTS-{version}-{status}.md"
    row = row_status or status
    p.write_text(
        "# AGENTS.md\n\n```\nPolicy-Version:      " + version + "\nStatus:              " + status + "\n```\n\n"
        "| Version | Date | Status | Class | Summary | Approval |\n|---|---|---|---|---|---|\n"
        f"| {version} | 2026-10-23 | {row} | MAJOR | claims mandatory | x |\n"
    )
    return p


def gate(tmp_path, b, paths, md, *, session="me", branch="feat/mine", override=None):
    return B.precommit_gate(b, paths, session=session, vendor="claude", branch=branch, agents_md=md, override=override)


@pytest.mark.parametrize(
    "version,status,row,enforce",
    [
        ("19.0.0", "ACTIVE", None, False),
        ("20.0.0", "PROPOSED", None, False),
        ("20.0.0", "ACTIVE", "PROPOSED", False),
        ("20.0.0", "ACTIVE", None, True),
        ("21.2.0", "ACTIVE", None, True),
    ],
)
def test_claim_policy_state_or_later(tmp_path, version, status, row, enforce):
    assert B.claim_policy_state(agents_md(tmp_path, version, status, row))["enforce"] is enforce


def test_claim_policy_state_unreadable_is_not_enforcing(tmp_path):
    st = B.claim_policy_state(tmp_path / "missing.md")
    assert st["state"] == B.POLICY_UNREADABLE and st["enforce"] is False


def test_gate_warns_below_20(tmp_path):
    b = board(tmp_path)
    mk(b, "other", ["docs"], branch="feat/theirs")
    res = gate(tmp_path, b, ["docs/a.md", "x.py"], agents_md(tmp_path, "19.0.0"))
    assert res["exit_code"] == 0 and res["mode"] == "warn"
    text = "\n".join(res["messages"])
    assert "WARN: docs/a.md held by" in text and "feat/theirs" in text and "since 2026-10-23T14:00:00Z" in text
    assert "no claim of this session" in text and "warn-only" in text


def test_gate_blocks_at_20_on_another_sessions_claim(tmp_path):
    b = board(tmp_path)
    mk(b, "me", ["docs/a.md"], branch="feat/mine")
    mk(b, "other", ["scripts/x.py"], branch="feat/theirs")
    res = gate(tmp_path, b, ["docs/a.md", "scripts/x.py"], agents_md(tmp_path, "20.0.0"))
    assert res["exit_code"] == 1 and res["mode"] == "enforce"
    text = "\n".join(res["messages"])
    assert "BLOCK: scripts/x.py held by claude/other-agent session other on branch feat/theirs since" in text
    assert res["uncovered"] == ["scripts/x.py"]


def test_gate_blocks_at_20_when_no_claim_held(tmp_path):
    b = board(tmp_path)
    res = gate(tmp_path, b, ["docs/a.md"], agents_md(tmp_path, "20.0.0"))
    assert res["exit_code"] == 1 and res["uncovered"] == ["docs/a.md"] and res["conflicts"] == []
    assert any("no claim of this session" in m for m in res["messages"])


def test_gate_passes_at_20_when_own_claim_covers(tmp_path):
    b = board(tmp_path)
    mkw(b, "me", ["docs", "scripts/**/*.py"], branch="feat/mine")
    res = gate(tmp_path, b, ["docs/a.md", "scripts/lib/x.py"], agents_md(tmp_path, "20.0.0"))
    assert res["exit_code"] == 0 and res["messages"] == []
    # covered by branch alone (no session env in the hook)
    res = gate(tmp_path, b, ["docs/a.md"], agents_md(tmp_path, "20.0.0"), session=None)
    assert res["exit_code"] == 0


def test_gate_merged_holder_no_longer_blocks(tmp_path):
    b = board(tmp_path)
    mkw(b, "me", ["docs"], branch="feat/mine")
    mk(board(tmp_path), "other", ["scripts/x.py"], branch="feat/theirs", pr="7")
    b.observer = observer(FakeGH(routes(pr_doc(merged=True))))
    res = gate(tmp_path, b, ["docs/a.md"], agents_md(tmp_path, "20.0.0"))
    assert res["exit_code"] == 0


def test_gate_override_is_logged_to_history(tmp_path):
    b = board(tmp_path)
    mk(b, "other", ["docs"], branch="feat/theirs")
    res = gate(tmp_path, b, ["docs/a.md"], agents_md(tmp_path, "20.0.0"), override="hotfix agreed with codex")
    assert res["exit_code"] == 0 and res["override"]["reason"] == "hotfix agreed with codex"
    lines = (tmp_path / "claims" / B.HISTORY_NAME).read_text().splitlines()
    rec = json.loads(lines[-1])
    assert rec["schema"] == B.OVERRIDE_SCHEMA and rec["session"] == "me" and rec["uncovered"] == ["docs/a.md"]
    assert rec["conflicts"][0]["branch"] == "feat/theirs"
    # the history stays readable for archived-claim lookups
    assert b.find_in_history("20261023T140000Z-claude-deadbeef") is None


def test_gate_override_refused_when_it_cannot_be_logged(tmp_path, monkeypatch):
    b = board(tmp_path)
    monkeypatch.setattr(B, "log_override", lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
    res = gate(tmp_path, b, ["docs/a.md"], agents_md(tmp_path, "20.0.0"), override="x")
    assert res["exit_code"] == 1 and any("could not be logged" in m for m in res["messages"])


def test_cli_precommit_exit_codes(tmp_path, capsys):
    base = ["--claims-dir", str(tmp_path / "claims"), "--no-gh", "--session", "me"]
    md19, md20 = agents_md(tmp_path, "19.0.0"), agents_md(tmp_path, "20.0.0")
    assert CLI.main([*base, "precommit", "--exclude-branch", "b", "--agents-md", str(md19), "--paths", "a.md"]) == 0
    assert (
        CLI.main([*base, "precommit", "--exclude-branch", "b", "--agents-md", str(md20), "--paths", "a.md"])
        == CLI.PRECOMMIT_BLOCK
    )


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


def _hook_repo(tmp_path: Path, version: str) -> Path:
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
    (repo / "AGENTS.md").write_text(agents_md(tmp_path, version).read_text())
    _git(repo, "init", "-q", "-b", "feat/mine")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("x")
    _git(repo, "add", "docs/a.md")
    return repo


def _run_hook(repo, claims, **env):
    e = {k: v for k, v in os.environ.items() if k != "TRADEAI_CLAIM_OVERRIDE"}
    e.update({"TRADEAI_AGENT_CLAIMS_DIR": str(claims), "AGENT_CLAIM_NO_GH": "1", "AGENT_CLAIM_SESSION": "me", **env})
    return subprocess.run(
        ["bash", str(repo / "scripts" / "agent_claim_precommit.sh")],
        cwd=repo,
        env=e,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.parametrize("version,rc", [("19.0.0", 0), ("20.0.0", 1)])
def test_hook_script_policy_gated(tmp_path, version, rc):
    repo = _hook_repo(tmp_path, version)
    claims = tmp_path / "claims"
    B.ClaimBoard(claims).claim(
        vendor="codex", session="other", agent=None, task="t", paths=["docs"], branch="feat/theirs"
    )
    proc = _run_hook(repo, claims)
    assert proc.returncode == rc, proc.stderr
    assert "docs/a.md held by codex" in proc.stderr and "feat/theirs" in proc.stderr


def test_hook_script_override_at_20(tmp_path):
    repo = _hook_repo(tmp_path, "20.0.0")
    claims = tmp_path / "claims"
    proc = _run_hook(repo, claims, TRADEAI_CLAIM_OVERRIDE="operator said so")
    assert proc.returncode == 0 and "OVERRIDE" in proc.stderr
    rec = json.loads((claims / B.HISTORY_NAME).read_text().splitlines()[-1])
    assert rec["reason"] == "operator said so" and rec["branch"] == "feat/mine"


@pytest.mark.parametrize("version,rc", [("19.0.0", 0), ("20.0.0", 1)])
def test_hook_script_crash_blocks_only_when_enforcing(tmp_path, version, rc):
    repo = _hook_repo(tmp_path, version)
    (repo / "scripts" / "lib" / "agent_claim_lifecycle.py").write_text("raise ImportError('broken')\n")
    proc = _run_hook(repo, tmp_path / "claims")
    # the gate cannot import; the hook reads the policy itself (stdlib only) and fails closed only when enforcing
    assert proc.returncode == rc and "could not run" in proc.stderr


# ------------------------------------------------------------------------------------------- registry


def test_ci_gate_registered():
    from scripts.lib import ci_gates

    doc = json.loads((ROOT / "config" / "ci_gates" / "agent_claim_lifecycle_20261023.json").read_text())
    ci_gates.validate(doc, stem="agent_claim_lifecycle_20261023")
    assert "tests/test_agent_claim_lifecycle_20261023.py" in doc["files"]
    assert "tests/test_agent_task_board_20261023.py" in doc["files"]


def test_ui_model_test_runs_in_build():
    pkg = json.loads((ROOT / "apps" / "command-center-v3" / "package.json").read_text())
    assert "src/lib/agentClaimLifecycle.test.ts" in pkg["scripts"]["build"]
