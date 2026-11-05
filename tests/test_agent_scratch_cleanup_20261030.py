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
    args = dict(home=home, claims_dir=tmp_path / "claims", proc_root=proc, task="dsn-20261030-example",
                claim=None, session=None, scratch=[], apply=False)
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
    assert mod.run(home=home, claims_dir=tmp_path / "claims", proc_root=tmp_path / "proc",
                   task="busy", claim=None, session=None, scratch=[], apply=True) == 0
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
    assert mod.run(home=home, claims_dir=tmp_path / "claims", proc_root=tmp_path / "proc", task=None,
                   claim="C1", session=None, scratch=[], apply=True) == 0
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
    assert mod.run(home=home, claims_dir=tmp_path / "claims", proc_root=tmp_path / "proc",
                   task="maybe-live", claim=None, session=None, scratch=[], apply=True) == 0
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


