"""Fail-closed worktree / Git identity assertion (SOP adversarial case).

Must run before leases, receipt persistence, generated files, mutating tests,
or source edits. Detects wrong-cwd, borrowed gitdir, release-dir Git metadata
that resolves to another registered worktree, HEAD mismatch, and unacked dirty.

Observed adversary: a verifier launched from a release directory whose ``.git``
file pointed at another checkout's gitdir. ``git`` reported that release as
``--show-toplevel`` and showed hundreds/thousands of phantom modifications,
while HEAD was the other worktree's commit — not the intended SOP tip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class WorktreeIdentityError(RuntimeError):
    """Aggregate identity failure; ``.errors`` holds machine-readable codes."""

    def __init__(self, errors: list[str]):
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


def _git_ok(args: list[str], *, cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 and proc.stderr:
        out = (proc.stderr or "").strip() or out
    return proc.returncode, out


def parse_worktree_porcelain(text: str) -> list[dict[str, str]]:
    """Parse ``git worktree list --porcelain`` into per-worktree dicts."""
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            if cur:
                entries.append(cur)
            cur = {"worktree": line[len("worktree ") :]}
        elif line.startswith("HEAD "):
            cur["HEAD"] = line[len("HEAD ") :]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch ") :]
        elif line == "detached":
            cur["detached"] = "1"
        elif line.startswith("bare"):
            cur["bare"] = "1"
    if cur:
        entries.append(cur)
    return entries


def list_registered_worktrees(cwd: Path) -> list[dict[str, str]]:
    rc, out = _git_ok(["worktree", "list", "--porcelain"], cwd=cwd)
    if rc != 0:
        return []
    return parse_worktree_porcelain(out)


def _resolve(p: Path | str) -> Path:
    return Path(p).resolve()


def _dedup(errors: list[str]) -> list[str]:
    out: list[str] = []
    for e in errors:
        if e not in out:
            out.append(e)
    return out


def _primary_worktree(registered: list[dict[str, str]], common: Path) -> Path | None:
    """Best-effort primary checkout path (owns the common ``.git`` directory)."""
    for ent in registered:
        wt = ent.get("worktree")
        if not wt:
            continue
        path = _resolve(wt)
        git_path = path / ".git"
        if git_path.is_dir() and git_path.resolve() == common:
            return path
        if common == path / ".git":
            return path
    # Fallback: common's parent if it appears in the list
    parent = common.parent if common.name == ".git" else None
    if parent is not None:
        for ent in registered:
            wt = ent.get("worktree")
            if wt and _resolve(wt) == parent:
                return parent
    return None


def assert_worktree_identity(
    *,
    expected_worktree: Path | str,
    cwd: Path | str | None = None,
    expected_head: str | None = None,
    acknowledge_dirty: bool = False,
    require_registered: bool = True,
) -> dict[str, Any]:
    """Return identity facts or raise ``WorktreeIdentityError``.

    Fail-closed codes (stable strings for tests / receipts):

    * ``CWD_NE_EXPECTED_WORKTREE``
    * ``TOPLEVEL_NE_EXPECTED_WORKTREE``
    * ``EXPECTED_NOT_IN_WORKTREE_LIST``
    * ``GITDIR_BELONGS_TO_OTHER_WORKTREE``
    * ``BORROWED_GITDIR_OR_RELEASE_DIR``
    * ``HEAD_NE_EXPECTED``
    * ``DIRTY_UNACKNOWLEDGED``
    * ``GIT_IDENTITY_UNAVAILABLE``
    """
    errors: list[str] = []
    expected = _resolve(expected_worktree)
    here = _resolve(cwd) if cwd is not None else Path.cwd().resolve()

    facts: dict[str, Any] = {
        "expected_worktree": str(expected),
        "cwd": str(here),
        "toplevel": None,
        "git_dir": None,
        "git_common_dir": None,
        "head": None,
        "dirty_lines": [],
        "worktree_list_match": None,
        "ok": False,
        "errors": errors,
    }

    if here != expected:
        errors.append("CWD_NE_EXPECTED_WORKTREE")

    rc_tl, toplevel_s = _git_ok(["rev-parse", "--show-toplevel"], cwd=here)
    if rc_tl != 0:
        errors.append("GIT_IDENTITY_UNAVAILABLE")
        raise WorktreeIdentityError(_dedup(errors))
    toplevel = _resolve(toplevel_s)
    facts["toplevel"] = str(toplevel)
    if toplevel != expected:
        errors.append("TOPLEVEL_NE_EXPECTED_WORKTREE")

    rc_gd, git_dir_s = _git_ok(["rev-parse", "--absolute-git-dir"], cwd=here)
    rc_cd, common_s = _git_ok(["rev-parse", "--git-common-dir"], cwd=here)
    if rc_gd != 0 or rc_cd != 0:
        errors.append("GIT_IDENTITY_UNAVAILABLE")
        raise WorktreeIdentityError(_dedup(errors))
    git_dir = _resolve(git_dir_s)
    common = _resolve(common_s) if Path(common_s).is_absolute() else _resolve(here / common_s)
    facts["git_dir"] = str(git_dir)
    facts["git_common_dir"] = str(common)

    registered = list_registered_worktrees(here)
    registered_paths = {_resolve(e["worktree"]) for e in registered if e.get("worktree")}

    match = None
    for ent in registered:
        wt = ent.get("worktree")
        if wt and _resolve(wt) == expected:
            match = ent
            break
    facts["worktree_list_match"] = match
    if require_registered and match is None:
        errors.append("EXPECTED_NOT_IN_WORKTREE_LIST")

    # Case: cwd/toplevel not a registered worktree path (release dir with
    # borrowed .git file). Git may still report cwd as toplevel.
    if here not in registered_paths or toplevel not in registered_paths:
        errors.append("BORROWED_GITDIR_OR_RELEASE_DIR")

    if here != toplevel:
        errors.append("BORROWED_GITDIR_OR_RELEASE_DIR")

    # Git directory belongs to another registered worktree.
    primary = _primary_worktree(registered, common)
    facts["primary_worktree"] = str(primary) if primary else None
    if primary is not None and git_dir == common and here != primary and expected != primary:
        # Using the primary gitdir from a non-primary path (classic release borrow).
        errors.append("GITDIR_BELONGS_TO_OTHER_WORKTREE")
    toplevel_ent_path = toplevel if toplevel in registered_paths else None
    if toplevel_ent_path is not None and toplevel_ent_path != expected:
        errors.append("GITDIR_BELONGS_TO_OTHER_WORKTREE")
    # Standing in registered WT-A while expecting WT-B.
    if here in registered_paths and here != expected:
        errors.append("GITDIR_BELONGS_TO_OTHER_WORKTREE")

    rc_head, head = _git_ok(["rev-parse", "HEAD"], cwd=here)
    if rc_head != 0:
        errors.append("GIT_IDENTITY_UNAVAILABLE")
        raise WorktreeIdentityError(_dedup(errors))
    facts["head"] = head
    if expected_head:
        exp = expected_head.strip().lower()
        got = head.strip().lower()
        if not (got == exp or (len(exp) >= 7 and got.startswith(exp))):
            errors.append("HEAD_NE_EXPECTED")

    rc_st, porcelain = _git_ok(["status", "--porcelain"], cwd=here)
    if rc_st != 0:
        errors.append("GIT_IDENTITY_UNAVAILABLE")
        raise WorktreeIdentityError(_dedup(errors))
    dirty_lines = [ln for ln in porcelain.splitlines() if ln.strip()]
    facts["dirty_lines"] = dirty_lines
    if dirty_lines and not acknowledge_dirty:
        errors.append("DIRTY_UNACKNOWLEDGED")

    facts["errors"] = _dedup(errors)
    if facts["errors"]:
        raise WorktreeIdentityError(facts["errors"])
    facts["ok"] = True
    return facts
