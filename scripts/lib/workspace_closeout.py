"""Archive-then-remove for a linked git worktree (AGENTS.md §24.14; DSN-20261030-workspace-lifecycle P2-T1).

One helper for ``disk_hygiene.py`` rule C (and later ``agent_claim.py close``). Archive: every tracked change,
untracked non-ignored file and HEAD are committed through a TEMPORARY index (the worktree's own index is never
touched; no hook or fsmonitor runs; fixed closeout identity) and pinned at ``<archive_ns>/<slug>-<hash>`` in the
shared repository. Ignored files are not kept (rebuildable by definition). Remove: ``git worktree remove --force``
from the main repo. Nothing is pushed; no branch, remote branch or ref is ever deleted.
Restore: ``git worktree add <path> <ref>``. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

IDENTITY = {"GIT_AUTHOR_NAME": "closeout", "GIT_AUTHOR_EMAIL": "closeout@localhost",
            "GIT_COMMITTER_NAME": "closeout", "GIT_COMMITTER_EMAIL": "closeout@localhost"}
SAFE = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")


def git(cwd: Path | str, *args: str, env: Optional[dict] = None, timeout: float = 600) -> tuple[int, str, str]:
    """git with no hooks/fsmonitor; (rc, stdout, stderr). Timeouts and a missing binary are failures, never success."""
    base = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    try:
        p = subprocess.run(["git", *SAFE, "-C", str(cwd), *args], capture_output=True, text=True, timeout=timeout,
                           env={**base, **(env or {})})
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as exc:
        return 127, "", type(exc).__name__
    return p.returncode, p.stdout, p.stderr


def ref_name(path: Path | str, archive_ns: str, home: Optional[Path] = None) -> str:
    """``<archive_ns>/<slug>-<sha256(path)[:10]>``; the slug never starts with ``.``/``_``/``-`` (git ref rules)."""
    p = os.path.abspath(str(path))
    h = str(home or Path.home()).rstrip("/") + "/"
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", p.removeprefix(h))[:180].lstrip("_-") or "root"
    return f"{archive_ns.rstrip('/')}/{slug}-{hashlib.sha256(p.encode()).hexdigest()[:10]}"


def archive_worktree(path: Path | str, archive_ns: str, note: str, *, home: Optional[Path] = None) -> tuple[Optional[dict], Optional[str]]:
    """Commit HEAD + tracked changes + untracked non-ignored files to an archive ref; ({ref, sha, tree}, None) or (None, why)."""
    p = os.path.abspath(str(path))
    ref = ref_name(p, archive_ns, home)
    rc, _, _ = git(p, "check-ref-format", ref, timeout=30)
    if rc != 0:
        return None, "ref_name_invalid"
    rc, head, _ = git(p, "rev-parse", "--verify", "-q", "HEAD", timeout=60)
    if rc != 0 or not head.strip():
        return None, "no_head"
    with tempfile.TemporaryDirectory(prefix="closeout-index-") as td:
        env = {"GIT_INDEX_FILE": os.path.join(td, "index")}
        for args in (("read-tree", "HEAD"), ("add", "-A")):
            rc, _, err = git(p, *args, env=env)
            if rc != 0:
                return None, f"{args[0]}_failed:{err.strip()[:200]}"
        rc, tree, err = git(p, "write-tree", env=env)
        if rc != 0 or not tree.strip():
            return None, "write_tree_failed:" + err.strip()[:200]
    rc, sha, err = git(p, "commit-tree", tree.strip(), "-p", head.strip(), "-m", f"closeout archive of {p}\n\n{note}", env=IDENTITY)
    if rc != 0 or not sha.strip():
        return None, "commit_tree_failed:" + err.strip()[:200]
    rc, _, err = git(p, "update-ref", ref, sha.strip(), timeout=60)
    if rc != 0:
        return None, "update_ref_failed:" + err.strip()[:200]
    rc, pinned, _ = git(p, "rev-parse", "--verify", "-q", ref, timeout=60)
    if rc != 0 or pinned.strip() != sha.strip():
        return None, "archive_ref_unverified"
    return {"ref": ref, "sha": sha.strip(), "tree": tree.strip(), "head": head.strip()}, None


def remove_worktree(path: Path | str, main_repo: Path | str) -> tuple[bool, str]:
    """``git worktree remove --force`` from the main repo (a locked worktree still refuses), then prune."""
    p = os.path.abspath(str(path))
    rc, _, err = git(main_repo, "worktree", "remove", "--force", p)
    if rc != 0 or os.path.lexists(p):
        return False, f"git_worktree_remove_rc:{rc}:{err.strip()[:160]}"
    prc, _, _ = git(main_repo, "worktree", "prune", timeout=60)
    return True, "git worktree remove --force" + ("; prune_failed" if prc else "; prune")
