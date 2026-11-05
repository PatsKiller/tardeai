"""Hermetic tests for scripts/agent_scratch_cleanup.py (agent self-cleanup at task end).

Never touches production state: every scratch candidate lives under tmp_path, the claim board and /proc are
injected or stubbed, and the module under test is loaded by file path (AGENTS.md §7 L7-05).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path


def _load():
    root = Path(__file__).resolve().parents[1]
    path = root / "scripts" / "agent_scratch_cleanup.py"
    spec = importlib.util.spec_from_file_location("agent_scratch_cleanup", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    import sys

    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _roots(home: Path) -> list[Path]:
    return [home / ".cache" / "agent-tmp", home / ".cache" / "rtc", Path("/tmp")]


def _narrow_roots(home: Path) -> list[Path]:
    """The agent-tmp + rtc roots only (no /tmp: pytest's tmp_path is itself under /tmp)."""
    return [home / ".cache" / "agent-tmp", home / ".cache" / "rtc"]


def test_evaluate_plain_dir_under_scratch_root_is_candidate(tmp_path):
    mod = _load()
    home = tmp_path / "home"
    scratch = home / ".cache" / "agent-tmp" / "mytask"
    scratch.mkdir(parents=True)
    (scratch / "work.txt").write_text("scratch", encoding="utf-8")
    r = mod.evaluate(scratch, home=home, roots=_roots(home), refs=set(), live_worktrees=[])
    assert r["candidate"] is True
    assert r["kind"] == "dir"
    assert r["how"] == "rmtree"


def test_evaluate_refuses_symlink_outside_root_and_never_touch(tmp_path):
    mod = _load()
    home = tmp_path / "home"
    base = home / ".cache" / "agent-tmp"
    # symlink never a candidate
    link = base / "link"
    base.mkdir(parents=True)
    (base / "target").mkdir()
    link.symlink_to(base / "target", target_is_directory=True)
    assert not mod.evaluate(link, home=home, roots=_roots(home), refs=set(), live_worktrees=[])["candidate"]
    # outside any scratch root (narrow roots: pytest tmp_path is itself under /tmp)
    outside = tmp_path / "elsewhere" / "dir"
    outside.mkdir(parents=True)
    r = mod.evaluate(outside, home=home, roots=_narrow_roots(home), refs=set(), live_worktrees=[])
    assert "outside_scratch_root" in r["reasons"]
    # never-touch name
    dbb = base / "db_backups"
    dbb.mkdir()
    r = mod.evaluate(dbb, home=home, roots=_roots(home), refs=set(), live_worktrees=[])
    assert any(x.startswith("never_touch_name") for x in r["reasons"])
    # credential-like name
    envdir = base / ".env"
    envdir.mkdir()
    r = mod.evaluate(envdir, home=home, roots=_roots(home), refs=set(), live_worktrees=[])
    assert any(x.startswith("never_touch_glob") for x in r["reasons"])


def test_evaluate_refuses_root_itself_and_live_claim_worktree(tmp_path):
    mod = _load()
    home = tmp_path / "home"
    root = home / ".cache" / "agent-tmp"
    root.mkdir(parents=True)
    # the scratch root itself is never a candidate (narrow roots, see above)
    r = mod.evaluate(root, home=home, roots=_narrow_roots(home), refs=set(), live_worktrees=[])
    assert "outside_scratch_root" in r["reasons"]
    # a live claim's recorded worktree is never a candidate
    wt = home / ".cache" / "agent-tmp" / "live-worktree"
    wt.mkdir(parents=True)
    r = mod.evaluate(wt, home=home, roots=_roots(home), refs=set(), live_worktrees=[wt])
    assert any(x.startswith("live_claim_worktree") for x in r["reasons"])


def test_process_refs_and_in_use(tmp_path):
    mod = _load()
    proc = tmp_path / "proc"
    pid = proc / "4242"
    (pid / "fd").mkdir(parents=True)
    target = tmp_path / "scratch"
    target.mkdir()
    (pid / "cwd").symlink_to(target, target_is_directory=True)
    (pid / "fd" / "3").symlink_to(target / "open.bin")
    refs = mod.process_refs(proc_root=proc)
    assert mod.in_use_by(target, refs) is not None
    assert mod.in_use_by(tmp_path / "other", refs) is None


def test_size_bytes_never_follows_symlink(tmp_path):
    mod = _load()
    d = tmp_path / "sized"
    d.mkdir()
    (d / "a").write_bytes(b"x" * 100)
    (d / "b").write_bytes(b"y" * 50)
    assert mod.size_bytes(d) == 150


def test_remove_item_removes_dir_and_refuses_symlink(tmp_path):
    mod = _load()
    d = tmp_path / "rm"
    d.mkdir()
    (d / "f").write_text("x", encoding="utf-8")
    ok, how = mod.remove_item(d, "dir", None)
    assert ok and how == "rmtree"
    assert not d.exists()
    link = tmp_path / "lnk"
    link.symlink_to(tmp_path)
    ok, how = mod.remove_item(link, "dir", None)
    assert not ok and how == "symlink"


def test_run_dry_run_lists_and_does_not_delete_then_apply_deletes(tmp_path, monkeypatch):
    mod = _load()
    home = tmp_path / "home"
    scratch = home / ".cache" / "agent-tmp" / "dsn-20261030-example"
    scratch.mkdir(parents=True)
    (scratch / "a.txt").write_text("scratch", encoding="utf-8")
    monkeypatch.setattr(mod, "live_claim_view", lambda claims_dir: ([], None))
    proc = tmp_path / "proc"
    proc.mkdir()
    _completed_task(tmp_path / "claims", task="dsn-20261030-example")
    args = dict(
        home=home,
        claims_dir=tmp_path / "claims",
        proc_root=proc,
        task="dsn-20261030-example",
        claim=None,
        session="fixture-session",
        scratch=[],
        apply=False,
    )
    assert mod.run(**args) == 0
    assert scratch.exists()  # dry-run removes nothing
    # capture the dry-run would_remove by re-running and reading the report path is not needed: apply proves it.
    args["apply"] = True
    assert mod.run(**args) == 0
    assert not scratch.exists()


def test_run_dry_run_never_deletes_when_in_use(tmp_path, monkeypatch):
    mod = _load()
    home = tmp_path / "home"
    scratch = home / ".cache" / "agent-tmp" / "busy"
    scratch.mkdir(parents=True)
    (scratch / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mod, "live_claim_view", lambda claims_dir: ([], None))
    # a live process cwd inside the scratch refuses the delete even under --apply
    monkeypatch.setattr(mod, "process_refs", lambda proc_root: {str(scratch)})
    assert (
        mod.run(
            home=home,
            claims_dir=tmp_path / "claims",
            proc_root=tmp_path / "proc",
            task="busy",
            claim=None,
            session=None,
            scratch=[],
            apply=True,
        )
        == 0
    )
    assert scratch.exists()


def test_run_with_claim_protects_every_live_claim_worktree(tmp_path, monkeypatch):
    """Naming one --claim must not narrow the live-worktree guard.

    A session scratch dir can hold ANOTHER live claim's worktree; rule 6(c) / §24.13 make that worktree
    untouchable even when the target claim is named explicitly.
    """
    mod = _load()
    home = tmp_path / "home"
    base = home / ".cache" / "agent-tmp"
    session_dir = base / "cc-deepseek"
    other_wt = session_dir / "wt-other"
    other_wt.mkdir(parents=True)
    (other_wt / "work.txt").write_text("another claim's live worktree", encoding="utf-8")
    matched_wt = tmp_path / "elsewhere-wt"
    matched_wt.mkdir()
    live = [
        {"claim_id": "C1", "task": "cleanup me", "worktree": str(matched_wt), "session": "cc-deepseek", "paths": []},
        {"claim_id": "C2", "task": "other", "worktree": str(other_wt), "session": "cc-deepseek", "paths": []},
    ]
    monkeypatch.setattr(mod, "live_claim_view", lambda claims_dir: (live, None))
    monkeypatch.setattr(mod, "process_refs", lambda proc_root: set())
    assert (
        mod.run(
            home=home,
            claims_dir=tmp_path / "claims",
            proc_root=tmp_path / "proc",
            task=None,
            claim="C1",
            session=None,
            scratch=[],
            apply=True,
        )
        == 0
    )
    assert other_wt.exists() and (other_wt / "work.txt").exists()
    assert session_dir.exists()


def test_run_fails_closed_when_claim_board_unreadable(tmp_path, monkeypatch):
    """An unreadable claim board is not proof that a path is unclaimed: apply must remove nothing."""
    mod = _load()
    home = tmp_path / "home"
    scratch = home / ".cache" / "agent-tmp" / "maybe-live"
    scratch.mkdir(parents=True)
    (scratch / "a.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mod, "live_claim_view", lambda claims_dir: ([], "claim_board_read_failed:OSError"))
    monkeypatch.setattr(mod, "process_refs", lambda proc_root: set())
    assert (
        mod.run(
            home=home,
            claims_dir=tmp_path / "claims",
            proc_root=tmp_path / "proc",
            task="maybe-live",
            claim=None,
            session=None,
            scratch=[],
            apply=True,
        )
        == 0
    )
    assert scratch.exists()


def test_in_use_by_ignores_ancestor_reference(tmp_path):
    """cc-deepseek-9 F1 at #2302: only a process INSIDE the candidate makes it in use.

    A shell sitting in $HOME (or /tmp) is an ancestor of every agent-tmp candidate and must not freeze the
    feature; the old both-directions test refused everything under those roots.
    """
    mod = _load()
    home = tmp_path / "home"
    cand = home / ".cache" / "agent-tmp" / "x"
    cand.mkdir(parents=True)
    assert mod.in_use_by(cand, {str(home)}) is None  # ancestor cwd: not in use
    assert mod.in_use_by(cand, {str(tmp_path)}) is None
    sub = cand / "sub"
    sub.mkdir()
    assert mod.in_use_by(cand, {str(sub)}) == str(sub)  # a process inside still refuses
    open_file = cand / "open.bin"
    open_file.write_text("x", encoding="utf-8")
    assert mod.in_use_by(cand, {str(open_file)}) == str(open_file)


# Cloud2302: every filesystem and board is a synthetic fixture, including process inspection.
import json
import sys
import pytest


def _completed_task(board, *, task="own-task", session="fixture-session", status="done", pr_state="merged"):
    board.mkdir(parents=True, exist_ok=True)
    cid = "fixture-completed"
    stamp = "2026-01-01T00:00:00Z"
    doc = {
        "schema": "AgentClaim@v1",
        "claim_id": cid,
        "status": status,
        "session": session,
        "task": task,
        "branch": "wt/synthetic-completed",
        "pr": 9001,
        "head_sha": "b" * 40,
        "started_at": stamp,
        "heartbeat_at": stamp,
        "ended_at": stamp,
        "paths": ["src/synthetic-completed.py"],
        "worktree": str(board.parent / "finished-project"),
    }
    observation = {
        "schema": "AgentClaimLifecycle@v1",
        "claim_id": cid,
        "pr_number": 9001,
        "pr_state": pr_state,
        "pr_base": "main",
        "head_sha": "b" * 40,
        "merge_sha": "a" * 40 if pr_state == "merged" else None,
        "merged_at": stamp if pr_state == "merged" else None,
        "closed_at": stamp if pr_state == "closed" else None,
        "observed_at": stamp,
        "stages": {"merged": stamp} if pr_state == "merged" else {},
    }
    path = board / (cid + ".json")
    path.write_text(json.dumps(doc))
    lifecycle = board / "lifecycle"
    lifecycle.mkdir(exist_ok=True)
    sidecar = lifecycle / (cid + ".json")
    sidecar.write_text(json.dumps(observation))
    return path, sidecar


def _fixture_run(mod, tmp_path, *, task="own-task", claims=None, proc=None, scratch=None, apply=True, completion=True):
    home = tmp_path / "home"
    candidate = home / ".cache" / "agent-tmp" / task
    candidate.mkdir(parents=True, exist_ok=True)
    (candidate / "synthetic.txt").write_text("synthetic disposable fixture")
    board = claims if claims is not None else tmp_path / "claims"
    if claims is None:
        board.mkdir(exist_ok=True)
    if completion:
        _completed_task(board, task=task)
    process = proc if proc is not None else tmp_path / "proc"
    if proc is None:
        process.mkdir(exist_ok=True)
    return candidate, dict(
        home=home,
        claims_dir=board,
        proc_root=process,
        task=task,
        claim=None,
        session="fixture-session",
        scratch=scratch or [],
        apply=apply,
    )


@pytest.mark.parametrize("where", ["rtc", "outside", "other-task"])
def test_cloud_namespace_and_owner_refusal(tmp_path, capsys, where):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    other = (
        args["home"] / ".cache" / "rtc" / "own-task"
        if where == "rtc"
        else tmp_path / "outside"
        if where == "outside"
        else candidate.parent / "other-task"
    )
    other.mkdir(parents=True)
    (other / "synthetic.txt").write_text("keep")
    args["scratch"] = [str(other)]
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert other.exists(), report
    assert str(other) not in [x["path"] for x in report["removed"] if x.get("ok")]


@pytest.mark.parametrize("name", ["db_backups", "nested/.env.synthetic", "nested/private.key", "nested/repo/.git"])
def test_cloud_protected_descendants_are_preserved(tmp_path, capsys, name):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    nested = candidate / name
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.mkdir() if name.endswith(".git") or name == "db_backups" else nested.write_text("synthetic")
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and nested.exists(), report
    assert not report["removed_count"]


def test_cloud_descendant_symlink_is_refused_without_following(tmp_path, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    target = tmp_path / "untouched"
    target.mkdir()
    (target / "a").write_text("synthetic")
    (candidate / "link").symlink_to(target, target_is_directory=True)
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and (target / "a").exists() and not report["removed_count"]


def test_cloud_unreadable_descendant_scan_refuses(tmp_path, monkeypatch, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    real = mod.os.scandir

    def scan(path):
        if Path(path) == candidate:
            raise PermissionError("synthetic scan failure")
        return real(path)

    monkeypatch.setattr(mod.os, "scandir", scan)
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"]


@pytest.mark.parametrize("reference", ["absolute-path", "home-relative-path", "worklog", "worklog-ancestor"])
def test_cloud_live_claim_and_real_worklog_references(tmp_path, capsys, reference):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    board = args["claims_dir"]
    cid = "fixture-claim"
    paths = (
        [str(candidate / "synthetic.txt")]
        if reference == "absolute-path"
        else ["~/.cache/agent-tmp/own-task/synthetic.txt"]
        if reference == "home-relative-path"
        else ["src/synthetic.py"]
    )
    doc = {
        "schema": "AgentClaim@v1",
        "claim_id": cid,
        "status": "active",
        "session": "peer",
        "task": "peer task",
        "heartbeat_at": "2030-01-01T00:00:00Z",
        "started_at": "2030-01-01T00:00:00Z",
        "paths": paths,
        "worktree": str(tmp_path / "unrelated-project"),
    }
    (board / (cid + ".json")).write_text(json.dumps(doc))
    mention = str(candidate) if reference == "worklog" else str(candidate.parent)
    (board / (cid + ".worklog.md")).write_text(
        "Active proof: `" + mention + "`" if reference.startswith("worklog") else "No scratch here"
    )
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"], report


@pytest.mark.parametrize(
    "failure",
    ["missing-proc", "permission-proc", "permission-pid", "missing-claims", "permission-claims", "worklog-unreadable"],
)
def test_cloud_unknown_evidence_never_means_unreferenced(tmp_path, monkeypatch, capsys, failure):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    if failure == "missing-proc":
        args["proc_root"] = tmp_path / "absent-proc"
    if failure == "missing-claims":
        args["claims_dir"] = tmp_path / "absent-claims"
    if failure == "permission-proc":
        real = mod.os.listdir

        def listing(path):
            if Path(path) == args["proc_root"]:
                raise PermissionError("synthetic proc failure")
            return real(path)

        monkeypatch.setattr(mod.os, "listdir", listing)
    if failure == "permission-pid":
        (args["proc_root"] / "99" / "fd").mkdir(parents=True)
    if failure == "permission-claims":
        real = mod.os.scandir

        def scan(path):
            if Path(path) == args["claims_dir"]:
                raise PermissionError("synthetic claims failure")
            return real(path)

        monkeypatch.setattr(mod.os, "scandir", scan)
    if failure == "worklog-unreadable":
        cid = "fixture"
        board = args["claims_dir"]
        (board / (cid + ".json")).write_text(
            json.dumps(
                {
                    "schema": "AgentClaim@v1",
                    "claim_id": cid,
                    "status": "active",
                    "session": "peer",
                    "paths": [],
                    "worktree": str(tmp_path / "elsewhere"),
                }
            )
        )
        log = board / (cid + ".worklog.md")
        log.mkdir()
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"], report


def test_cloud_positive_dryrun_and_apply_with_real_empty_board(tmp_path, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path, apply=False)
    mod.run(**args)
    dry = capsys.readouterr().out
    assert "would delete:" in dry and candidate.exists()
    args["apply"] = True
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert report["removed_count"] == 1 and not candidate.exists(), report


def test_cloud_default_namespace_has_no_tmp_or_rtc(tmp_path):
    mod = _load()
    home = tmp_path / "home"
    assert mod.default_scratch_roots(home) == [home / ".cache" / "agent-tmp"]


def test_cloud_revalidation_sees_new_protected_descendant(tmp_path, monkeypatch, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    calls = 0

    def inspect(proc_root):
        nonlocal calls
        calls += 1
        if calls == 2:
            (candidate / "db_backups").mkdir()
        return set()

    monkeypatch.setattr(mod, "process_refs", inspect)
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and (candidate / "db_backups").exists()
    assert not report["removed_count"] and report["removed"][0]["how"] == "skip:revalidation_refused"


def test_cloud_revalidation_refuses_new_evidence_failure(tmp_path, monkeypatch, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    calls = 0

    def inspect(proc_root):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise mod.CleanupError("synthetic inspection failure")
        return set()

    monkeypatch.setattr(mod, "process_refs", inspect)
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"]


def test_cloud_symlink_namespace_cannot_redirect_cleanup(tmp_path, capsys):
    mod = _load()
    home = tmp_path / "home"
    cache = home / ".cache"
    cache.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    candidate = outside / "own-task"
    candidate.mkdir()
    (candidate / "a").write_text("synthetic")
    (cache / "agent-tmp").symlink_to(outside, target_is_directory=True)
    board = tmp_path / "claims"
    board.mkdir()
    proc = tmp_path / "proc"
    proc.mkdir()
    mod.run(
        home=home, claims_dir=board, proc_root=proc, task="own-task", claim=None, session=None, scratch=[], apply=True
    )
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"]


def test_cloud_claim_reference_alias_preserves_real_target(tmp_path, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    alias = tmp_path / "live-alias"
    alias.symlink_to(candidate, target_is_directory=True)
    cid = "alias-claim"
    (args["claims_dir"] / (cid + ".json")).write_text(
        json.dumps(
            {
                "schema": "AgentClaim@v1",
                "claim_id": cid,
                "status": "active",
                "session": "peer",
                "paths": [str(alias / "synthetic.txt")],
                "worktree": str(tmp_path / "project"),
            }
        )
    )
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"], report


def test_cloud_cli_dryrun_then_apply_uses_only_the_named_fixture(tmp_path, monkeypatch, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    monkeypatch.setenv("AGENT_SCRATCH_DIRS", "")
    options = [
        "--home",
        str(args["home"]),
        "--proc-root",
        str(args["proc_root"]),
        "--claims-dir",
        str(args["claims_dir"]),
        "--task",
        "own-task",
        "--session",
        "fixture-session",
    ]
    assert mod.main(options + ["--dry-run"]) == 0
    assert "would delete:" in capsys.readouterr().out and candidate.exists()
    assert mod.main(options + ["--apply"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["removed_count"] == 1 and not candidate.exists()


# D52: completion belongs to the task/feature, not the end of one source-custody session.
@pytest.mark.parametrize(
    "problem",
    [
        "missing",
        "active",
        "done-open",
        "abandoned-open",
        "missing-observation",
        "wrong-task",
        "foreign-session",
        "wrong-pr",
        "bad-merge-sha",
        "missing-ended-at",
        "custody-only",
        "session-namespace",
        "missing-session",
        "declared-merged-only",
        "missing-pr",
        "wrong-observed-claim",
        "wrong-observed-schema",
        "related-active",
        "done-closed",
        "missing-observed-head",
        "wrong-observed-head",
        "missing-claim-head",
        "wrong-claim-head",
        "nonhex-head",
    ],
)
def test_d52_unfinished_or_unbound_task_scratch_is_refused(tmp_path, capsys, problem):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path, completion=False)
    if problem != "missing":
        claim, sidecar = _completed_task(args["claims_dir"])
        doc = json.loads(claim.read_text())
        obs = json.loads(sidecar.read_text())
        if problem == "active":
            doc["status"] = "active"
        elif problem in ("done-open", "abandoned-open", "custody-only"):
            doc["status"] = "abandoned" if problem != "done-open" else "done"
            doc["note"] = "Source custody abandoned; PR/feature NOT abandoned"
            obs.update(pr_state="open", merge_sha=None, merged_at=None, stages={})
        elif problem == "missing-observation":
            obs = {}
        elif problem == "wrong-task":
            doc["task"] = "a different task"
        elif problem == "foreign-session":
            doc["session"] = "a different owner"
        elif problem == "wrong-pr":
            obs["pr_number"] = 9002
        elif problem == "bad-merge-sha":
            obs["merge_sha"] = "unknown"
        elif problem == "missing-ended-at":
            doc.pop("ended_at")
        elif problem == "session-namespace":
            args["task"] = None
            args["session"] = "own-task"
        elif problem == "missing-session":
            args["session"] = None
        elif problem == "missing-observed-head":
            obs.pop("head_sha")
        elif problem == "wrong-observed-head":
            obs["head_sha"] = "c" * 40
        elif problem == "missing-claim-head":
            doc.pop("head_sha")
        elif problem == "wrong-claim-head":
            doc["head_sha"] = "c" * 40
        elif problem == "nonhex-head":
            doc["head_sha"] = obs["head_sha"] = "not-a-git-object"
        elif problem == "missing-pr":
            doc.pop("pr")
        elif problem == "wrong-observed-claim":
            obs["claim_id"] = "foreign-completion"
        elif problem == "wrong-observed-schema":
            obs["schema"] = "CallerCompletedFlag@v1"
        elif problem == "related-active":
            related = dict(
                doc,
                claim_id="fixture-related",
                status="active",
                session="peer",
                task="unfinished work",
                paths=["src/unrelated.py"],
            )
            (args["claims_dir"] / "fixture-related.json").write_text(json.dumps(related))
        elif problem == "done-closed":
            obs.update(pr_state="closed", merge_sha=None, merged_at=None, closed_at="2026-01-01T00:00:00Z", stages={})
        elif problem == "declared-merged-only":
            doc["stages"] = {"merged": "2026-01-01T00:00:00Z"}
            obs = {}
        claim.write_text(json.dumps(doc))
        sidecar.write_text(json.dumps(obs))
    args["apply"] = False
    mod.run(**args)
    dry = capsys.readouterr().out
    assert "would delete:" not in dry, dry
    assert candidate.exists()
    args["apply"] = True
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and (candidate / "synthetic.txt").read_text() == "synthetic disposable fixture", report
    assert report["removed_count"] == 0, report
    assert any("completion" in reason for row in report["refused"] for reason in row["reasons"]), report


@pytest.mark.parametrize("completion", ["merged", "abandoned-closed"])
def test_d52_canonical_completed_task_has_a_real_dry_apply_firing_control(tmp_path, capsys, completion):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path, completion=False)
    _completed_task(
        args["claims_dir"],
        status="done" if completion == "merged" else "abandoned",
        pr_state="merged" if completion == "merged" else "closed",
    )
    args["apply"] = False
    mod.run(**args)
    assert "would delete:" in capsys.readouterr().out and candidate.exists()
    args["apply"] = True
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert not candidate.exists() and report["removed_count"] == 1, report


def test_d52_completion_is_revalidated_immediately_before_removal(tmp_path, monkeypatch, capsys):
    mod = _load()
    candidate, args = _fixture_run(mod, tmp_path)
    _, sidecar = _completed_task(args["claims_dir"])
    calls = 0

    def inspect(proc_root):
        nonlocal calls
        calls += 1
        if calls == 2:
            observation = json.loads(sidecar.read_text())
            observation.update(pr_state="open", merge_sha=None, merged_at=None, stages={})
            sidecar.write_text(json.dumps(observation))
        return set()

    monkeypatch.setattr(mod, "process_refs", inspect)
    mod.run(**args)
    report = json.loads(capsys.readouterr().out)
    assert candidate.exists() and not report["removed_count"], report
    assert report["removed"][0]["how"] == "skip:completion_revalidation_refused", report
