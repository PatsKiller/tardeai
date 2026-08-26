"""CURRENT pin integrity — fail if the live tree is not one commit.

CURRENT is not a git repo. Compare its scripts/ + docs/ trees to
SOURCE_COMMIT via git --work-tree. A docs overlay on an older pin is
the same disease as ~80 services on the rebuild tree.

READ_ONLY_ADVISORY. No broker mutation. No LLM calls.
"""
from __future__ import annotations

import json
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


def _git(repo: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Always `git -C repo`. Never `--work-tree=CURRENT` — that binds the
    rebuild branch index/sparse-checkout and false-fires D on live files."""
    cmd = ["git", "-C", str(repo), *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def _git_bytes(repo: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess[bytes]:
    cmd = ["git", "-C", str(repo), *args]
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def collect_pin_report(*, now: Optional[datetime] = None) -> dict[str, Any]:
    import hashlib
    import tarfile
    from io import BytesIO

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
    git_dir = repo / ".git"
    if not git_dir.exists() and not repo.joinpath(".git").is_file():
        # worktree gitfile still counts
        row = evaluate_pin(
            source_commit=sha, diff_paths=[], extra_paths=[], git_error="repo_git_missing"
        )
        row["as_of"] = now.replace(microsecond=0).isoformat()
        row["current_dir"] = str(cur)
        row["repo"] = str(repo)
        return row

    tree = _git(repo, "ls-tree", "-r", "--name-only", sha, "--", *TREES)
    if tree.returncode != 0:
        err = (tree.stderr or tree.stdout or "ls-tree_failed").strip().splitlines()
        row = evaluate_pin(
            source_commit=sha,
            diff_paths=[],
            extra_paths=[],
            git_error=(err[0] if err else "ls-tree_failed")[:80],
        )
        row["as_of"] = now.replace(microsecond=0).isoformat()
        return row
    tracked = {ln.strip() for ln in (tree.stdout or "").splitlines() if ln.strip() and not _skip(ln.strip())}

    arch = _git_bytes(repo, "archive", sha, "--", *TREES)
    if arch.returncode != 0:
        row = evaluate_pin(
            source_commit=sha,
            diff_paths=[],
            extra_paths=[],
            git_error="archive_failed",
        )
        row["as_of"] = now.replace(microsecond=0).isoformat()
        return row

    expected: dict[str, bytes] = {}
    with tarfile.open(fileobj=BytesIO(arch.stdout), mode="r:") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            rel = m.name
            if _skip(rel):
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            expected[rel] = f.read()

    diffs: list[str] = []
    for rel, blob in expected.items():
        disk = cur / rel
        if not disk.is_file():
            diffs.append(rel)
            continue
        try:
            data = disk.read_bytes()
        except OSError:
            diffs.append(rel)
            continue
        if hashlib.sha256(data).digest() != hashlib.sha256(blob).digest():
            diffs.append(rel)

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

    row = evaluate_pin(source_commit=sha, diff_paths=diffs, extra_paths=extras)
    row["as_of"] = now.replace(microsecond=0).isoformat()
    row["current_dir"] = str(cur.resolve())
    row["repo"] = str(repo)
    return row


def boot_stamp_path() -> Path:
    override = os.getenv("PORTFOLIO_SERVER_BOOT_STAMP_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "state" / "tradeai" / "portfolio_server_boot.json"


def _pin_changed_at(cur: Path) -> Optional[datetime]:
    candidates: list[datetime] = []
    for path, follow in ((cur, False), (cur / "SOURCE_COMMIT", True)):
        try:
            stat = path.stat() if follow else path.lstat()
            candidates.append(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc))
        except OSError:
            continue
    return max(candidates) if candidates else None


def collect_process_freshness(*, now: Optional[datetime] = None) -> dict[str, Any]:
    """Alarm when the running :7777 process predates the pin or loaded a different SHA.

    Same class as last_real / [:500] / stale attach cache: a lagged view served as now.
    """
    now = now or datetime.now(timezone.utc)
    cur = current_dir()
    disk_sha = read_source_commit(cur) if cur.is_dir() else ""
    stamp_path = boot_stamp_path()
    firing: list[str] = []
    loaded = ""
    started = ""
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8")) if stamp_path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        stamp = {}
    if not stamp:
        firing.append("boot_stamp_missing")
    else:
        loaded = str(stamp.get("loaded_pin_sha") or "")
        started = str(stamp.get("process_started_at") or "")
        if disk_sha and loaded and loaded != disk_sha:
            firing.append("loaded_pin_ne_current_pin")
        try:
            pin_mtime = _pin_changed_at(cur)
            if started:
                st = datetime.fromisoformat(started.replace("Z", "+00:00"))
                if st.tzinfo is None:
                    st = st.replace(tzinfo=timezone.utc)
                if pin_mtime and st < pin_mtime:
                    firing.append("process_predates_pin")
        except (OSError, ValueError):
            pass
    return {
        "lane": "process-freshness",
        "ok": not firing,
        "firing": firing,
        "loaded_pin_sha": loaded or None,
        "current_pin_sha": disk_sha or None,
        "process_started_at": started or None,
        "current_pin_changed_at": _pin_changed_at(cur).replace(microsecond=0).isoformat()
            if _pin_changed_at(cur) else None,
        "boot_stamp": str(stamp_path) if stamp_path.is_file() else None,
        "authority": AUTHORITY,
        "schema": "ProcessFreshness@v1",
        "as_of": now.replace(microsecond=0).isoformat(),
    }
