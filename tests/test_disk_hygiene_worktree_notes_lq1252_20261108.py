"""ANCHOR: DISK_HYGIENE_WORKTREE_NOTES_LQ1252_20261108 — LQ-20261107-1252 (P0 disk): rule W reclaims a linked
worktree at 24 h, or when a closeout note names it.

Synthetic temp repositories only: a real `git init` + `git worktree add` give a real clean/in-use/dirty
tree without touching the host. The note index is built from a synthetic coordination root; no host
census, no PR call, no DB, no credential read. The one removal test acts on its own temp repo.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import disk_hygiene as DH
from scripts.lib import disk_hygiene_retention as SR

NOW = datetime(2026, 11, 8, 22, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ("DONE-", "REVIEW-")
NOTE_DIR = "coordinator/inbox/claude-lead"  # relative to the coordination root, as in config


# ── synthetic git fixtures ────────────────────────────────────────────────────────────────────────────────────────


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
           "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
           "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd)}
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def _main_repo(tmp_path: Path) -> Path:
    """A synthetic canonical repo with an owned remote and an origin/main ref."""
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    (main / "README.md").write_text("synthetic fixture\n")
    _git(main, "add", "README.md")
    _git(main, "commit", "-qm", "base")
    _git(main, "remote", "add", "origin", "https://github.com/PatsKiller/tardeai.git")
    head = _git(main, "rev-parse", "HEAD").strip()
    _git(main, "update-ref", "refs/remotes/origin/main", head)
    return main


def _worktree(main: Path, home: Path, name: str = "tradeai-wt-synthetic", branch: str = "wt/synthetic") -> Path:
    wt = home / name
    _git(main, "worktree", "add", "-q", "-b", branch, str(wt))
    return wt


def _gitdir(main: Path, wt: Path) -> Path:
    return main / ".git" / "worktrees" / wt.name


def _stamp(path: Path, hours: float) -> None:
    """Set every entry (and the root) to NOW - hours, so SR.activity is deterministic."""
    stamp = (NOW - timedelta(hours=hours)).timestamp()
    for dirpath, dirnames, filenames in os.walk(path):
        for name in dirnames + filenames:
            try:
                os.utime(os.path.join(dirpath, name), (stamp, stamp), follow_symlinks=False)
            except OSError:
                pass
    os.utime(path, (stamp, stamp), follow_symlinks=False)


def _age(main: Path, wt: Path, hours: float) -> None:
    _stamp(wt, hours)
    _stamp(_gitdir(main, wt), hours)


# ── rules + evidence fixtures ────────────────────────────────────────────────────────────────────────────────────


def _rules(tmp_path: Path, *, worktree: dict | None = None) -> dict:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    cfg = json.loads((ROOT / "config/disk_hygiene_rules.json").read_text())
    standing = {
        "enabled": True, "rules": ["W"], "manifest_max_age_hours": 2,
        "max_bytes_per_run": SR.MAX_BYTES, "max_gb_per_run": 40, "byte_unit": "GiB",
        "approved_by": "SYNTHETIC_TEST_ONLY",
        "archive": {"path": "~/db_backups/archive"},
        "approval": {"status": "APPROVED", "approved_by": "SYNTHETIC_TEST_ONLY",
                     "approved_at": NOW.isoformat()},
    }
    if worktree is not None:
        standing["worktree"] = worktree
    cfg["standing_apply"] = standing
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(cfg))
    return DH.load_rules(rules_path, home=home)


def _note(path: str, mtime: float, *, paths=(), branches=()) -> dict:
    return {"path": path, "mtime": mtime, "paths": list(paths), "branches": list(branches)}


def _evidence(*, notes=None, complete=True, cwds=()) -> dict:
    co = {"references": [], "live_claims": [], "live_worklogs": [],
          "closeout_notes": list(notes or []), "closeout_notes_complete": complete}
    vals = {"cron": "# synthetic fixture\n", "units": [],
            "processes": [{"pid": str(i), "cwd": str(c)} for i, c in enumerate(cwds)],
            "coordination": co, "prs": [], "pointers": []}
    return {"schema": SR.SCHEMA, "offline": False, "sources": {
        k: {"complete": True, "captured_at": NOW.isoformat(), "data": v, "sha256": SR.digest(v)}
        for k, v in vals.items()}}


def _rows(rules: dict, monkeypatch, tree: Path, doc: dict) -> list[dict]:
    monkeypatch.setattr(DH, "discover_git_dirs", lambda *_: [tree])
    return DH.standing_results(rules, SR.evidence_context(doc, NOW))


def _wt_row(rules: dict, monkeypatch, tree: Path, doc: dict) -> dict:
    return next(r for r in _rows(rules, monkeypatch, tree, doc) if r["path"] == str(tree))


# ── scan_coordination: the closeout-note index ───────────────────────────────────────────────────────────────────


def _coord(tmp_path: Path) -> Path:
    base = tmp_path / "coordination"
    (base / "claims").mkdir(parents=True)
    (base / "worklogs").mkdir()
    (base / "handoffs").mkdir()
    (base / "handoffs" / "PROGRESS_LOG.md").write_text("progress log\n")
    (base / NOTE_DIR).mkdir(parents=True)
    return base


def test_scan_coordination_indexes_done_and_review_notes_only(tmp_path):
    base = _coord(tmp_path)
    branch = "wt/lq9999-synthetic"
    path = str(tmp_path / "tradeai-wt-lq9999-synthetic")
    done = base / NOTE_DIR / "DONE-LQ-9999-fixture.md"
    done.write_text(f"# DONE\n- worktree {path}\n- branch **`{branch}`**\n")
    review = base / NOTE_DIR / "REVIEW-LQ-9998-fixture.md"
    review.write_text("- branch `lq9998/other`\n")
    # Not a closeout note: wrong prefix, wrong suffix, or one level deeper.
    (base / NOTE_DIR / "NOTE-LQ-9997.md").write_text(f"- worktree {path}\n")
    (base / NOTE_DIR / "DONE-LQ-9996.json").write_text("{}\n")
    (base / NOTE_DIR / "archive").mkdir()
    (base / NOTE_DIR / "archive" / "DONE-LQ-9995.md").write_text(f"- worktree {path}\n")

    os.utime(done, (NOW.timestamp() - 3600, NOW.timestamp() - 3600))
    out = DH.scan_coordination(base, NOW, closeout_note_dirs=[NOTE_DIR], closeout_note_prefixes=list(PREFIXES))

    assert out["closeout_notes_complete"] is True
    notes = {n["path"]: n for n in out["closeout_notes"]}
    assert set(notes) == {f"{NOTE_DIR}/{done.name}", f"{NOTE_DIR}/{review.name}"}
    assert path in notes[f"{NOTE_DIR}/{done.name}"]["paths"]
    assert branch in notes[f"{NOTE_DIR}/{done.name}"]["branches"]
    assert notes[f"{NOTE_DIR}/{done.name}"]["mtime"] == pytest.approx(NOW.timestamp() - 3600, abs=2)
    assert "lq9998/other" in notes[f"{NOTE_DIR}/{review.name}"]["branches"]
    # The closeout index never rewrites the live-reference hold set.
    assert set(out) >= {"references", "live_claims", "live_worklogs", "archived_files"}


def test_scan_coordination_without_note_config_is_unchanged(tmp_path):
    base = _coord(tmp_path)
    (base / NOTE_DIR / "DONE-LQ-9999-fixture.md").write_text("- anything\n")
    out = DH.scan_coordination(base, NOW)
    assert out["closeout_notes"] == []
    assert out["closeout_notes_complete"] is True


def test_unreadable_note_dir_is_incomplete_and_never_waives(tmp_path):
    base = _coord(tmp_path)
    (base / NOTE_DIR / "DONE-LQ-9999-fixture.md").write_text("- anything\n")
    note_dir = base / NOTE_DIR
    os.chmod(note_dir, 0)
    try:
        if os.access(note_dir, os.R_OK):  # root ignores the mode bits
            pytest.skip("running with privileges that bypass directory permissions")
        out = DH.scan_coordination(base, NOW, closeout_note_dirs=[NOTE_DIR],
                                   closeout_note_prefixes=list(PREFIXES))
        assert out["closeout_notes_complete"] is False
        assert out["closeout_notes"] == []
    finally:
        os.chmod(note_dir, stat.S_IRWXU)


# ── rule W: the 24 h floor, and the note that waives it ─────────────────────────────────────────────────────────


def test_worktree_younger_than_24h_is_held_by_the_configured_floor(tmp_path, monkeypatch):
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24})
    home = rules["_home"]
    wt = _worktree(main, home)
    _age(main, wt, 20)

    row = _wt_row(rules, monkeypatch, wt, _evidence())
    assert row["candidate"] is False
    assert "worktree_not_untouched_24h" in row["reasons"]
    assert wt.exists()


def test_worktree_older_than_24h_is_a_candidate_under_rule_w(tmp_path, monkeypatch):
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24})
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 30)

    row = _wt_row(rules, monkeypatch, wt, _evidence())
    assert row["candidate"] is True, row["reasons"]
    assert row["rule"] == "W" and row["kind"] == "git_worktree"


def test_default_floor_stays_48h_when_the_block_is_absent(tmp_path, monkeypatch):
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path)
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 30)

    row = _wt_row(rules, monkeypatch, wt, _evidence())
    assert row["candidate"] is False
    assert "worktree_not_untouched_48h" in row["reasons"]


@pytest.mark.parametrize("named", ["paths", "branches"])
def test_closeout_note_waives_the_age_floor_when_it_names_the_worktree(tmp_path, monkeypatch, named):
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24, "closeout_note_waives_age": True})
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 2)
    activity, why = SR.activity(wt)
    assert why is None and activity is not None
    note = _note(f"{NOTE_DIR}/DONE-LQ-9999-fixture.md", NOW.timestamp() - 3600,
                 paths=[str(wt)] if named == "paths" else [],
                 branches=["wt/synthetic"] if named == "branches" else [])

    row = _wt_row(rules, monkeypatch, wt, _evidence(notes=[note]))
    assert row["candidate"] is True, row["reasons"]
    assert row["evidence"]["closeout_note"] == note["path"]


def test_note_matches_by_exact_identity_not_by_prefix(tmp_path, monkeypatch):
    """A sibling path or a longer branch in the note waives nothing: the match is set membership, not a prefix."""
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24, "closeout_note_waives_age": True})
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 2)

    sibling = _note(f"{NOTE_DIR}/DONE-LQ-9999-fixture.md", NOW.timestamp() - 3600,
                    paths=[f"{wt}-2"], branches=["wt/synthetic-two", "wt"])
    held = _wt_row(rules, monkeypatch, wt, _evidence(notes=[sibling]))
    assert held["candidate"] is False
    assert "worktree_not_untouched_24h" in held["reasons"]


def test_a_note_written_before_the_worktree_last_moved_does_not_waive(tmp_path, monkeypatch):
    """Workers keep one worktree across tickets, so a DONE note for an earlier ticket names a tree that may still be
    in use. If anything in the tree moved after the note, the note no longer vouches for it: the 24 h floor binds."""
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24, "closeout_note_waives_age": True})
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 2)  # last activity ~2 h ago; the note is 3 h old
    note = _note(f"{NOTE_DIR}/DONE-LQ-9999-fixture.md", NOW.timestamp() - 3 * 3600,
                 paths=[str(wt)], branches=["wt/synthetic"])

    row = _wt_row(rules, monkeypatch, wt, _evidence(notes=[note]))
    assert row["candidate"] is False
    assert "worktree_not_untouched_24h" in row["reasons"]


def test_incomplete_note_scan_never_waives_the_floor(tmp_path, monkeypatch):
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24, "closeout_note_waives_age": True})
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 2)
    note = _note(f"{NOTE_DIR}/DONE-LQ-9999-fixture.md", NOW.timestamp() - 3600, branches=["wt/synthetic"])

    row = _wt_row(rules, monkeypatch, wt, _evidence(notes=[note], complete=False))
    assert row["candidate"] is False
    assert "worktree_not_untouched_24h" in row["reasons"]


def test_a_note_waiver_never_overrides_clean_or_in_use_or_live_claim_holds(tmp_path, monkeypatch):
    main = _main_repo(tmp_path)
    rules = _rules(tmp_path, worktree={"untouched_hours": 24, "closeout_note_waives_age": True})
    wt = _worktree(main, rules["_home"])
    _age(main, wt, 2)
    note = _note(f"{NOTE_DIR}/DONE-LQ-9999-fixture.md", NOW.timestamp() - 3600,
                 paths=[str(wt)], branches=["wt/synthetic"])

    # (a) dirty: the note cannot make a dirty tree a candidate, and the reason says why.
    (wt / "README.md").write_text("fixture changed after the note\n")
    dirty = _wt_row(rules, monkeypatch, wt, _evidence(notes=[note]))
    assert dirty["candidate"] is False
    assert "dirty" in dirty["reasons"]
    _git(wt, "checkout", "--", "README.md")
    _age(main, wt, 2)

    # (b) a process cwd inside it.
    in_use = _wt_row(rules, monkeypatch, wt, _evidence(notes=[note], cwds=[wt]))
    assert in_use["candidate"] is False
    assert "in_use_cwd" in in_use["reasons"]

    # (c) a live claim still holds the path through the coordination references.
    doc = _evidence(notes=[note])
    doc["sources"]["coordination"]["data"]["live_claims"] = [{"worktree": str(wt)}]
    doc["sources"]["coordination"]["sha256"] = SR.digest(doc["sources"]["coordination"]["data"])
    held = _wt_row(rules, monkeypatch, wt, doc)
    assert held["candidate"] is False
    assert any(r.startswith("referenced") for r in held["reasons"])


def test_removal_uses_worktree_remove_and_deletes_no_branch_or_commit(tmp_path):
    main = _main_repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    wt = _worktree(main, home)
    head = _git(wt, "rev-parse", "HEAD").strip()

    ok, how = DH.remove_item({"path": str(wt), "kind": "git_worktree", "main_repo": str(main)})

    assert ok and how.startswith("git worktree remove")
    assert not os.path.lexists(wt)
    # the branch, its commit and the canonical repo are untouched
    assert _git(main, "rev-parse", "--verify", "refs/heads/wt/synthetic").strip() == head
    assert _git(main, "cat-file", "-e", head) == ""
    assert (main / "README.md").exists()


# ── config validation ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("worktree,reason", [
    ({"untouched_hours": 0}, "worktree_untouched_hours"),
    ({"untouched_hours": "24"}, "worktree_untouched_hours"),
    ({"untouched_hours": 24, "closeout_note_waives_age": "yes"}, "worktree_closeout_note_waives_age"),
    ({"untouched_hours": 24, "closeout_note_dirs": ["/etc"]}, "worktree_closeout_note_dirs"),
    ({"untouched_hours": 24, "closeout_note_dirs": ["inbox/../../etc"]}, "worktree_closeout_note_dirs"),
    ({"untouched_hours": 24, "closeout_note_prefixes": ["DONE/x"]}, "worktree_closeout_note_prefixes"),
])
def test_bad_worktree_config_fails_closed(tmp_path, worktree, reason):
    with pytest.raises(DH.RulesError, match=reason):
        _rules(tmp_path, worktree=worktree)
