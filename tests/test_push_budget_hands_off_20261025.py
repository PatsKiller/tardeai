"""Hands-off delivery push mechanics (AGENTS.md 20.4.0, 2026-10-25; inert until 20.4.0 is ACTIVE on origin/main).

Operator 2026-10-25: "fully done, fully automatic, no input by me, for the train systems unless there's an issue."
* budget 2 -> 5 per branch only while 20.4.0 is ACTIVE in origin/main:AGENTS.md (never the branch's own copy);
* TRADEAI_REMOTE_PUSH_OVERRIDE stands without a fresh interactive approval only for the coordinator (live
  coordinator claim + Operator-approval: reference in the PR body or the coordinator's claim plan);
* every used override is logged; a force push / remote branch deletion is refused under any override."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import agent_claim_board as CB  # noqa: E402
from scripts.lib import hands_off_policy as H  # noqa: E402
from scripts.lib import tradeai_push_budget as B  # noqa: E402

PRE_PUSH = ROOT / ".githooks" / "pre-push"


def agents_md(version: str = "20.4.0", status: str = "ACTIVE", row: str | None = None, extra_rows: str = "") -> str:
    row = row if row is not None else status
    return (
        "# AGENTS.md\n\n```\nPolicy-Version:      "
        + version
        + "\nStatus:              "
        + status
        + "\nEffective-Date:      2026-10-26\n```\n\n| Version | Date | Status | Class | Change |\n|---|---|---|---|---|\n"
        + f"| {version} | 2026-10-26 | {row} | MINOR | hands-off delivery | x |\n"
        + extra_rows
        + "| 20.2.0 | 2026-10-24 | ACTIVE | MINOR | prior | x |\n"
    )


ACTIVE = {"active": True, "state": "ACTIVE", "detail": "test"}
INACTIVE = {"active": False, "state": "NOT_ACTIVE", "detail": "test"}


# ----------------------------------------------------------------------------------------------- the policy gate


@pytest.mark.parametrize(
    "text,expected",
    [
        (agents_md(), True),
        (agents_md(status="PROPOSED"), False),
        (agents_md(status="ACTIVE", row="PROPOSED"), False),
        (agents_md(version="20.3.0"), False),
        # Renumbered: the hands-off rules were ratified as 21.0.0 (PR #2128); no | 20.4.0 | row exists.
        (agents_md(version="21.0.0"), True),
        (agents_md(version="21.0.0", status="PROPOSED"), False),
        (agents_md(version="21.0.0", status="ACTIVE", row="PROPOSED"), False),
        (agents_md(version="20.3.0", status="PROPOSED"), False),
        # A later version is judged by ITS OWN row; a stale PROPOSED 20.4.0 row elsewhere does not matter.
        (agents_md(version="21.0.0", extra_rows="| 20.4.0 | 2026-10-26 | PROPOSED | MINOR | hands-off | x |\n"), True),
        ("", False),
        ("no control block", False),
    ],
)
def test_policy_state_from_text(text, expected):
    assert H.policy_state_from_text(text)["active"] is expected


def test_policy_has_no_environment_switch(monkeypatch):
    for name in ("TRADEAI_HANDS_OFF", "HANDS_OFF_ACTIVE", "TRADEAI_POLICY_20_4_0"):
        monkeypatch.setenv(name, "1")
    assert H.policy_state_from_text(agents_md(status="PROPOSED"))["active"] is False


def _git(cwd: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env).stdout.strip()


def test_git_state_reads_main_not_the_branch(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    (repo / "AGENTS.md").write_text(agents_md(status="PROPOSED"))
    _git(repo, "add", "AGENTS.md")
    _git(repo, "commit", "-qm", "proposed")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    # The branch self-promotes its own copy: it must arm nothing.
    _git(repo, "checkout", "-qb", "feat/x")
    (repo / "AGENTS.md").write_text(agents_md())
    _git(repo, "commit", "-qam", "self-promote")
    assert H.policy_state_from_path(repo / "AGENTS.md")["active"] is True  # the branch copy says ACTIVE...
    st = H.policy_state_from_git("origin/main", cwd=repo)
    assert st["active"] is False and st["source"] == "git:origin/main:AGENTS.md"  # ...main does not
    assert H.policy_state_from_git("origin/nope", cwd=repo)["active"] is False  # missing ref -> fail closed


# ----------------------------------------------------------------------------------------------- budget 5


def test_budget_is_two_until_active_then_five():
    assert B.budget_for("feat/x") == 2
    assert B.budget_for("feat/x", hands_off=True) == B.HANDS_OFF_BUDGET == 5
    assert B.budget_for(None, hands_off=True) == 5
    assert B.decide(authorized=True, override=False, count=2, branch="feat/x")["reason"] == "BUDGET_EXCEEDED"
    assert B.decide(authorized=True, override=False, count=4, branch="feat/x", hands_off=True)["allow"] is True
    sixth = B.decide(authorized=True, override=False, count=5, branch="feat/x", hands_off=True)
    assert sixth["allow"] is False and sixth["budget"] == 5
    assert (
        B.decide(authorized=False, override=True, count=0, branch="feat/x", hands_off=True)["reason"] == "UNAUTHORIZED"
    )


# ----------------------------------------------------------------------------------------------- coordinator


def _rows(*, session="coord-1", state="live", branch="feat/x", note=None, coord=True):
    rows = []
    if coord:
        rows.append(
            {"claim_id": "c1", "session": session, "paths": [H.COORDINATOR_CLAIM_PATH], "_state": state, "branch": None}
        )
    rows.append(
        {
            "claim_id": "c2",
            "session": session,
            "paths": ["scripts/x.py"],
            "_state": "live",
            "branch": branch,
            "note": note,
        }
    )
    return rows


def _pr(body):
    return lambda b: [{"number": 7, "body": body, "headRefName": b}]


ENV = {"TRADEAI_COORDINATOR_SESSION": "coord-1", "AGENT_CLAIM_SESSION": "coord-1"}


def test_coordinator_with_pr_body_approval_is_ok():
    v = B.coordinator_override(
        ["feat/x"],
        env=ENV,
        claim_rows=_rows(),
        pr_reader=_pr("Summary\n\nOperator-approval: TRACKER_20261024 item 7\n"),
    )
    assert v["ok"] is True and v["approvals"]["feat/x"] == {"ref": "TRACKER_20261024 item 7", "source": "pr#7 body"}


def test_coordinator_with_claim_plan_approval_is_ok():
    v = B.coordinator_override(
        ["feat/x"], env=ENV, claim_rows=_rows(note="Operator-approval: 10-25 chat 14:02"), pr_reader=lambda b: None
    )
    assert v["ok"] is True and v["approvals"]["feat/x"]["source"] == "claim plan"
    v = B.coordinator_override(
        ["feat/x"],
        env=ENV,
        claim_rows=_rows(),
        pr_reader=lambda b: [],
        worklog_reader=lambda r: "## Plan\n- [ ] Operator-approval: operator 10-25 #7\n",
    )
    assert v["ok"] is True


@pytest.mark.parametrize(
    "env,rows,body,why",
    [
        ({}, _rows(), "Operator-approval: x", "not set"),
        (
            {"TRADEAI_COORDINATOR_SESSION": "coord-1", "AGENT_CLAIM_SESSION": "other"},
            _rows(),
            "Operator-approval: x",
            "not the coordinator session",
        ),
        (ENV, _rows(coord=False), "Operator-approval: x", "no LIVE coordinator claim"),
        (ENV, _rows(state="stale"), "Operator-approval: x", "no LIVE coordinator claim"),
        (ENV, _rows(session="someone-else"), "Operator-approval: x", "no LIVE coordinator claim"),
        (ENV, _rows(), "no approval line", "no Operator-approval"),
        (ENV, _rows(), "Operator-approval: <ref>", "no Operator-approval"),
        (ENV, _rows(), "Operator-approval: TBD", "no Operator-approval"),
    ],
)
def test_coordinator_refusals(env, rows, body, why):
    v = B.coordinator_override(["feat/x"], env=env, claim_rows=rows, pr_reader=_pr(body))
    assert v["ok"] is False and why in v["why"]


def test_every_pushed_branch_needs_an_approval_ref():
    reader = lambda b: [{"number": 1, "body": "Operator-approval: ok" if b == "feat/x" else "", "headRefName": b}]
    v = B.coordinator_override(["feat/x", "feat/y"], env=ENV, claim_rows=_rows(), pr_reader=reader)
    assert v["ok"] is False and "feat/y" in v["why"]


def test_coordinator_claim_read_from_a_real_board(tmp_path):
    board = CB.ClaimBoard(tmp_path / "claims")
    board.claim(vendor="claude", session="coord-1", agent="c", task="coordinator", paths=[H.COORDINATOR_CLAIM_PATH])
    board.claim(
        vendor="claude",
        session="coord-1",
        agent="c",
        task="pr",
        paths=["scripts/x.py"],
        branch="feat/x",
        note="Operator-approval: TRACKER item 3",
    )
    rows = H._claim_rows(tmp_path / "claims")
    v = B.coordinator_override(["feat/x"], env=ENV, claim_rows=rows, pr_reader=lambda b: [])
    assert v["ok"] is True and v["coordinator_claim"]
    # The board keeps the coordinator path exclusive: a second session cannot also hold it.
    with pytest.raises(Exception):
        board.claim(vendor="codex", session="other", agent="x", task="coordinator", paths=[H.COORDINATOR_CLAIM_PATH])
    assert len(H.coordinator_claims(H._claim_rows(tmp_path / "claims"))) == 1


# ----------------------------------------------------------------------------------------------- hook decision


@pytest.fixture
def budget_file(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADEAI_PUSH_BUDGET_PATH", str(tmp_path / "budget.json"))
    monkeypatch.setenv("TRADEAI_PUSH_OVERRIDE_LOG", str(tmp_path / "overrides.jsonl"))
    return tmp_path


REFS = "refs/heads/feat/x " + "1" * 40 + " refs/heads/feat/x " + "2" * 40 + "\n"
FF = lambda refs: []  # noqa: E731


def _spent(n, branch="feat/x"):
    for _ in range(n):
        B.record_authorized_push(branch)


def test_inactive_never_consults_the_coordinator(budget_file):
    _spent(2)
    called = []
    d = B.hook_decision(
        REFS,
        authorized=True,
        env_override=True,
        env=ENV,
        hands_off=INACTIVE,
        coordinator_fn=lambda *a, **k: called.append(1),
        force_fn=FF,
    )
    assert d["allow"] is True and d["override_source"] == "env" and d["budget"] == 2 and not called


def test_active_third_push_needs_no_override(budget_file):
    _spent(2)
    d = B.hook_decision(REFS, authorized=True, env_override=False, env={}, hands_off=ACTIVE, force_fn=FF)
    assert d["allow"] is True and d["reason"] == "AUTHORIZED" and d["budget"] == 5 and not d["override_used"]
    _spent(3)
    d = B.hook_decision(REFS, authorized=True, env_override=False, env={}, hands_off=ACTIVE, force_fn=FF)
    assert d["allow"] is False and d["reason"] == "BUDGET_EXCEEDED"


def test_active_override_by_coordinator_is_attributed(budget_file):
    _spent(5)
    ok = lambda branches, env: {"ok": True, "session": "coord-1", "approvals": {"feat/x": {"ref": "r"}}, "why": "w"}
    d = B.hook_decision(
        REFS, authorized=True, env_override=True, env=ENV, hands_off=ACTIVE, coordinator_fn=ok, force_fn=FF
    )
    assert d["allow"] is True and d["override_source"] == "coordinator" and d["override_used"] is True
    bad = lambda branches, env: {"ok": False, "why": "no LIVE coordinator claim"}
    d = B.hook_decision(
        REFS, authorized=True, env_override=True, env=ENV, hands_off=ACTIVE, coordinator_fn=bad, force_fn=FF
    )
    # Not the coordinator: the env override is the operator's interactive approval, as before 20.4.0.
    assert d["allow"] is True and d["override_source"] == "env" and d["coordinator"]["why"]


def test_force_push_refused_under_any_override_and_whenever_active(budget_file):
    _spent(2)
    force = lambda refs: [{"branch": "feat/x", "why": "not a fast-forward"}]
    d = B.hook_decision(REFS, authorized=True, env_override=True, env={}, hands_off=INACTIVE, force_fn=force)
    assert d["allow"] is False and d["reason"] == "FORCE_PUSH_REFUSED"
    d = B.hook_decision(REFS, authorized=True, env_override=False, env={}, hands_off=ACTIVE, force_fn=force)
    assert d["allow"] is False and d["reason"] == "FORCE_PUSH_REFUSED"
    # Pre-20.4.0, no override in play: unchanged behaviour (the hook never looked at fast-forwards).
    d = B.hook_decision(REFS, authorized=True, env_override=False, env={}, hands_off=INACTIVE, force_fn=force)
    assert d["reason"] == "BUDGET_EXCEEDED"


def test_force_push_refusals_classifies_refs():
    refs = B.parse_push_refs(
        "refs/heads/a " + "0" * 40 + " refs/heads/a " + "3" * 40 + "\n"  # delete
        "refs/heads/b " + "1" * 40 + " refs/heads/b " + "0" * 40 + "\n"  # new branch
        "refs/heads/c " + "1" * 40 + " refs/heads/c " + "2" * 40 + "\n"  # non-ff
        "refs/heads/d " + "1" * 40 + " refs/heads/d " + "4" * 40 + "\n"  # unknown remote object
        "refs/heads/e " + "1" * 40 + " refs/heads/e " + "5" * 40 + "\n"  # fast-forward
    )
    verdict = {"2" * 40: False, "4" * 40: None, "5" * 40: True}
    out = B.force_push_refusals(refs, is_ancestor=lambda old, new: verdict[old])
    assert [o["branch"] for o in out] == ["a", "c", "d"]
    assert "force push" in out[1]["why"] and "fetch" in out[2]["why"]


def test_log_override_appends(budget_file):
    B.log_override({"source": "coordinator", "branches": [{"branch": "feat/x"}]})
    B.log_override({"source": "env", "branches": [{"branch": "feat/x"}]})
    rows = [json.loads(x) for x in (budget_file / "overrides.jsonl").read_text().splitlines()]
    assert [r["source"] for r in rows] == ["coordinator", "env"] and rows[0]["schema"] == B.OVERRIDE_LOG_SCHEMA


# ----------------------------------------------------------------------------------------------- the real hook


def _run(cmd, cwd, env=None, check=False):
    full = os.environ.copy()
    for k in (
        "TRADEAI_REMOTE_PUSH_AUTHORIZED",
        "TRADEAI_REMOTE_PUSH_OVERRIDE",
        "TRADEAI_COORDINATOR_SESSION",
        "AGENT_CLAIM_SESSION",
        "TRADEAI_AGENT_CLAIMS_DIR",
        "TRADEAI_PUSH_BUDGET_PATH",
        "TRADEAI_PUSH_OVERRIDE_LOG",
        "TRADEAI_REMOTE_PUSH_OVERRIDE_REF",
    ):
        full.pop(k, None)
    full.update(env or {})
    return subprocess.run(cmd, cwd=cwd, env=full, capture_output=True, text=True, check=check, timeout=120)


def _mini_repo(tmp: Path, *, policy: str) -> tuple[Path, dict]:
    src, remote = tmp / "src", tmp / "remote.git"
    src.mkdir()
    _run(["git", "init", "-q", "--bare", str(remote)], cwd=tmp, check=True)
    _run(["git", "init", "-q", "-b", "main"], cwd=src, check=True)
    _run(["git", "config", "user.email", "t@t.local"], cwd=src, check=True)
    _run(["git", "config", "user.name", "t"], cwd=src, check=True)
    (src / ".githooks").mkdir()
    shutil.copy2(PRE_PUSH, src / ".githooks/pre-push")
    os.chmod(src / ".githooks/pre-push", os.stat(src / ".githooks/pre-push").st_mode | stat.S_IEXEC)
    lib = src / "scripts" / "lib"
    lib.mkdir(parents=True)
    for name in (
        "tradeai_push_budget.py",
        "hands_off_policy.py",
        "agent_claim_board.py",
        "agent_claim_lifecycle.py",
        "agent_claim_worklog.py",
        "agent_file_lease.py",
        "__init__.py",
    ):
        if (ROOT / "scripts/lib" / name).exists():
            shutil.copy2(ROOT / "scripts/lib" / name, lib / name)
    (src / "scripts/check_no_secrets.py").write_text("import sys\nsys.exit(0)\n")
    (src / "AGENTS.md").write_text(policy)
    (src / "README").write_text("mini\n")
    _run(["git", "add", "."], cwd=src, check=True)
    _run(["git", "commit", "-qm", "init"], cwd=src, check=True)
    _run(["git", "remote", "add", "origin", str(remote)], cwd=src, check=True)
    _run(["git", "config", "core.hooksPath", ".githooks"], cwd=src, check=True)
    _run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=src, check=True)
    _run(["git", "checkout", "-qb", "feat/x"], cwd=src, check=True)
    fakebin = tmp / "bin"
    fakebin.mkdir()
    (fakebin / "gh").write_text("#!/bin/sh\necho '[]'\n")  # GitHub is never contacted by the test
    os.chmod(fakebin / "gh", 0o755)
    env = {
        "TRADEAI_SKIP_SECRETS_SCAN": "1",
        "TRADEAI_PUSH_BUDGET_PATH": str(src / ".git/budget.json"),
        "TRADEAI_PUSH_OVERRIDE_LOG": str(tmp / "overrides.jsonl"),
        "TRADEAI_REMOTE_PUSH_AUTHORIZED": "1",
        "TRADEAI_AGENT_CLAIMS_DIR": str(tmp / "claims"),
        "HOME": str(tmp / "home"),
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "TRADEAI_GUARD_CONSUME": "0",
    }
    return src, env


def _commit_push(src, env, n, *extra):
    (src / "README").write_text(f"push {n}\n")
    _run(["git", "commit", "-qam", f"push {n}"], cwd=src, check=True)
    return _run(["git", "push", *extra, "-u", "origin", "feat/x"], cwd=src, env=env)


def test_hook_five_pushes_when_active_then_coordinator_override_logged(tmp_path):
    src, env = _mini_repo(tmp_path, policy=agents_md())
    for n in range(1, 6):
        p = _commit_push(src, env, n)
        assert p.returncode == 0, (n, p.stderr)
        assert "budget=5 hands_off=True" in p.stdout
    sixth = _commit_push(src, env, 6)
    assert sixth.returncode != 0 and "Effective budget for this branch is 5." in sixth.stderr
    # The coordinator, with a live coordinator claim and an Operator-approval: line in its claim plan.
    board = CB.ClaimBoard(tmp_path / "claims")
    board.claim(vendor="claude", session="coord-1", agent="c", task="coordinator", paths=[H.COORDINATOR_CLAIM_PATH])
    board.claim(
        vendor="claude",
        session="coord-1",
        agent="c",
        task="pr",
        paths=["README"],
        branch="feat/x",
        note="Operator-approval: operator 2026-10-25 hands-off directive",
    )
    over = {
        **env,
        "TRADEAI_REMOTE_PUSH_OVERRIDE": "1",
        "TRADEAI_COORDINATOR_SESSION": "coord-1",
        "AGENT_CLAIM_SESSION": "coord-1",
        "TRADEAI_REMOTE_PUSH_OVERRIDE_REF": "operator 2026-10-25 hands-off directive",
    }
    p = _run(["git", "push", "origin", "feat/x"], cwd=src, env=over)
    assert p.returncode == 0, p.stderr
    assert "source=coordinator" in p.stdout
    log = [json.loads(x) for x in (tmp_path / "overrides.jsonl").read_text().splitlines()]
    assert log[-1]["source"] == "coordinator" and log[-1]["coordinator_ok"] is True
    assert log[-1]["approvals"]["feat/x"]["ref"] == "operator 2026-10-25 hands-off directive"
    assert log[-1]["override_ref"] == "operator 2026-10-25 hands-off directive"  # 21.0.0 §28.15 item 1
    # A force push is refused even for the coordinator with the override.
    _run(["git", "commit", "-q", "--amend", "-m", "rewritten"], cwd=src, check=True)
    forced = _run(["git", "push", "--force", "origin", "feat/x"], cwd=src, env=over)
    assert forced.returncode != 0 and "force push refused" in forced.stderr


def test_hook_unchanged_while_proposed(tmp_path):
    src, env = _mini_repo(tmp_path, policy=agents_md(status="PROPOSED"))
    for n in (1, 2):
        assert _commit_push(src, env, n).returncode == 0
    third = _commit_push(src, env, 3)
    assert third.returncode != 0 and "Effective budget for this branch is 2." in third.stderr
    # The operator's own override still works exactly as before -- and is now logged.
    p = _run(["git", "push", "origin", "feat/x"], cwd=src, env={**env, "TRADEAI_REMOTE_PUSH_OVERRIDE": "1"})
    assert p.returncode == 0, p.stderr
    log = [json.loads(x) for x in (tmp_path / "overrides.jsonl").read_text().splitlines()]
    assert log[-1]["source"] == "env" and log[-1]["hands_off"] is False


def test_hook_branch_cannot_self_activate(tmp_path):
    src, env = _mini_repo(tmp_path, policy=agents_md(status="PROPOSED"))
    (src / "AGENTS.md").write_text(agents_md())  # the branch claims ACTIVE; origin/main still says PROPOSED
    _run(["git", "commit", "-qam", "self-activate"], cwd=src, check=True)
    for n in (1, 2):
        assert _commit_push(src, env, n).returncode == 0
    assert _commit_push(src, env, 3).returncode != 0
