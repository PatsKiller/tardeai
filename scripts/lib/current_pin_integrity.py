"""CURRENT pin integrity — fail if the live tree is not one commit.

CURRENT is not a git repo. Compare its scripts/ + docs/ trees to
SOURCE_COMMIT via git --work-tree. A docs overlay on an older pin is
the same disease as ~80 services on the rebuild tree.

READ_ONLY_ADVISORY. No broker mutation. No LLM calls.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
SCHEMA = "CurrentPinIntegrity@v1"
DEFAULT_CURRENT = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"
DEFAULT_REPO = Path.home() / "trade-ai-v12-rebuild" / "trade-ai-v12-rebuild"
TREES = ("scripts", "docs")
# Runtime / generated — never part of the pin.
SKIP_PARTS = {
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "dist",
    ".vite",
    "logs",
}


def current_dir() -> Path:
    return Path(os.getenv("CURRENT_PIN_DIR") or DEFAULT_CURRENT).expanduser()


def repo_dir() -> Path:
    return Path(os.getenv("CURRENT_PIN_REPO") or DEFAULT_REPO).expanduser()


def read_source_commit(cur: Path) -> str:
    for name in ("SOURCE_COMMIT", "BUILD_SHA", "GIT_SHA"):
        p = cur / name
        if p.is_file():
            sha = p.read_text(encoding="utf-8").strip().split()[0]
            if sha:
                return sha
    return ""


def _skip(rel: str) -> bool:
    parts = Path(rel).parts
    return any(p in SKIP_PARTS for p in parts) or rel.endswith(".pyc")


def evaluate_pin(
    *,
    source_commit: str,
    diff_paths: Iterable[str],
    extra_paths: Iterable[str],
    missing_commit: bool = False,
    git_error: str = "",
) -> dict[str, Any]:
    """Pure evaluator — unit-testable without a live CURRENT."""
    diffs = [p for p in diff_paths if p and not _skip(p)]
    extras = [p for p in extra_paths if p and not _skip(p)]
    firing: list[str] = []
    if missing_commit:
        firing.append("missing_SOURCE_COMMIT")
    if git_error:
        firing.append(f"git_error:{git_error[:80]}")
    if diffs:
        firing.append(f"tree_diff:{len(diffs)}")
    if extras:
        firing.append(f"unpinned_extra:{len(extras)}")
    if not source_commit and not missing_commit:
        firing.append("empty_SOURCE_COMMIT")
    return {
        "lane": "current-pin",
        "ok": not firing,
        "firing": firing,
        "source_commit": source_commit,
        "diff_count": len(diffs),
        "extra_count": len(extras),
        "diff_sample": diffs[:20],
        "extra_sample": extras[:20],
        "authority": AUTHORITY,
        "schema": SCHEMA,
    }


def _git(repo: Path, *args: str, work_tree: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    cmd = ["git"]
    if work_tree is not None:
        cmd += [f"--git-dir={repo / '.git'}", f"--work-tree={work_tree}"]
    else:
        cmd += ["-C", str(repo)]
    cmd += list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def collect_pin_report(*, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    cur = current_dir()
    repo = repo_dir()
    sha = read_source_commit(cur) if cur.is_dir() else ""
    if not cur.is_dir():
        row = evaluate_pin(
            source_commit=sha,
            diff_paths=[],
            extra_paths=[],
            missing_commit=not sha,
            git_error="CURRENT_dir_missing",
        )
        row["as_of"] = now.replace(microsecond=0).isoformat()
        row["current_dir"] = str(cur)
        return row
    if not sha:
        row = evaluate_pin(source_commit="", diff_paths=[], extra_paths=[], missing_commit=True)
        row["as_of"] = now.replace(microsecond=0).isoformat()
        row["current_dir"] = str(cur)
        return row
    if not (repo / ".git").exists():
        row = evaluate_pin(
            source_commit=sha, diff_paths=[], extra_paths=[], git_error="repo_git_missing"
        )
        row["as_of"] = now.replace(microsecond=0).isoformat()
        row["current_dir"] = str(cur)
        row["repo"] = str(repo)
        return row

    diff = _git(repo, "diff", "--name-only", sha, "--", *TREES, work_tree=cur)
    if diff.returncode not in (0, 1):
        row = evaluate_pin(
            source_commit=sha,
            diff_paths=[],
            extra_paths=[],
            git_error=(diff.stderr or diff.stdout or "diff_failed").strip().splitlines()[0]
            if (diff.stderr or diff.stdout)
            else "diff_failed",
        )
        row["as_of"] = now.replace(microsecond=0).isoformat()
        return row
    diff_paths = [ln.strip() for ln in (diff.stdout or "").splitlines() if ln.strip()]

    tree = _git(repo, "ls-tree", "-r", "--name-only", sha, "--", *TREES)
    tracked = {ln.strip() for ln in (tree.stdout or "").splitlines() if ln.strip() and not _skip(ln.strip())}
    extras: list[str] = []
    for tree_name in TREES:
        root = cur / tree_name
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(cur)).replace("\\", "/")
            if _skip(rel):
                continue
            if rel not in tracked:
                extras.append(rel)

    row = evaluate_pin(source_commit=sha, diff_paths=diff_paths, extra_paths=extras)
    row["as_of"] = now.replace(microsecond=0).isoformat()
    row["current_dir"] = str(cur.resolve())
    row["repo"] = str(repo)
    return row
