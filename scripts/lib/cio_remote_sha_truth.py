"""Resolve remote Git SHA truth independently of a stale origin/main ref.

The acceptance runner must not award G1 because a local tracking ref is stale.
This module fetches, ls-remote's, and optionally cross-checks GitHub.

Authority: READ_ONLY_ADVISORY. No book mutation. No Telegram.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.cio_release_manifest import PIN_ONLY_PATHS, pin_only_parent

AUTHORITY = "READ_ONLY_ADVISORY"
CLASS_RUNTIME = "RUNTIME_CONTENT"
CLASS_ATTESTATION = "RELEASE_ATTESTATION_ONLY"
CLASS_UNKNOWN = "UNKNOWN"

# Canonical acceptance auditor files. G0 compares these blobs to remote main
# (attestation-only pin commits may touch RELEASE_MANIFEST* only).
ACCEPTANCE_EVALUATOR_RELPATH = "scripts/lib/cio_acceptance_v4.py"
ACCEPTANCE_RUNNER_RELPATH = "scripts/run_cio_acceptance.py"
ACCEPTANCE_EVALUATOR_FILES = (
    ACCEPTANCE_EVALUATOR_RELPATH,
    ACCEPTANCE_RUNNER_RELPATH,
)
ATTESTATION_ALLOWLIST_PATHS = frozenset(PIN_ONLY_PATHS)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(cmd: list[str], *, cwd: Optional[Path] = None, timeout: int = 40) -> tuple[int, str, str]:
    try:
        p = subprocess.run(
            cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", f"{type(e).__name__}:{e}"[:200]


def fetch_origin(repo: Path) -> dict[str, Any]:
    """git fetch --prune origin. Does not mutate working-tree files."""
    if os.environ.get("CIO_ACCEPTANCE_SKIP_FETCH", "").strip() in ("1", "true", "yes"):
        return {"ok": True, "skipped": True, "reason": "CIO_ACCEPTANCE_SKIP_FETCH"}
    code, out, err = _run(["git", "-C", str(repo), "fetch", "--prune", "origin"], timeout=90)
    return {"ok": code == 0, "skipped": False, "stdout": out[:400], "stderr": err[:400]}


def ls_remote_main(repo: Path) -> dict[str, Any]:
    code, out, err = _run(["git", "-C", str(repo), "ls-remote", "origin", "refs/heads/main"])
    sha = ""
    if code == 0 and out:
        sha = out.split()[0].strip()
    return {"ok": bool(sha) and len(sha) >= 12, "sha": sha, "stderr": err[:200]}


def local_origin_main(repo: Path) -> str:
    code, out, _err = _run(["git", "-C", str(repo), "rev-parse", "origin/main"])
    return out if code == 0 else ""


def github_main_sha() -> dict[str, Any]:
    if os.environ.get("CIO_ACCEPTANCE_SKIP_GITHUB", "").strip() in ("1", "true", "yes"):
        return {"ok": True, "skipped": True, "sha": ""}
    code, out, err = _run([
        "gh", "api", "repos/PatsKiller/tardeai/commits/main", "--jq", ".sha",
    ], timeout=25)
    sha = out.strip() if code == 0 else ""
    return {"ok": bool(sha), "sha": sha, "stderr": err[:200], "skipped": False}


def classify_main(repo: Path, remote_sha: str) -> dict[str, Any]:
    """RUNTIME_CONTENT vs RELEASE_ATTESTATION_ONLY vs UNKNOWN."""
    if not remote_sha:
        return {"class": CLASS_UNKNOWN, "first_parent": "", "changed": [], "ok": False}
    code, parents, _ = _run(["git", "-C", str(repo), "rev-parse", f"{remote_sha}^1"])
    first_parent = parents if code == 0 else ""
    code2, diff, _ = _run(["git", "-C", str(repo), "diff", "--name-only", f"{first_parent}..{remote_sha}"])
    changed = [ln.strip() for ln in (diff or "").splitlines() if ln.strip()] if code2 == 0 else []
    extra = sorted(set(changed) - set(PIN_ONLY_PATHS))
    if first_parent and changed and not extra:
        pin = pin_only_parent(remote_sha, first_parent)
        return {
            "class": CLASS_ATTESTATION,
            "first_parent": first_parent,
            "changed": changed,
            "extra": extra,
            "pin_only": bool(pin.get("ok")),
            "attested_runtime_content_sha": first_parent,
            "ok": bool(pin.get("ok")),
        }
    if first_parent and extra:
        return {
            "class": CLASS_RUNTIME,
            "first_parent": first_parent,
            "changed": changed,
            "extra": extra,
            "pin_only": False,
            "attested_runtime_content_sha": remote_sha,
            "ok": True,
        }
    if remote_sha:
        return {
            "class": CLASS_RUNTIME,
            "first_parent": first_parent,
            "changed": changed,
            "extra": extra,
            "pin_only": False,
            "attested_runtime_content_sha": remote_sha,
            "ok": True,
        }
    return {"class": CLASS_UNKNOWN, "first_parent": "", "changed": [], "ok": False}


def resolve_remote_sha_truth(repo: Path, *, fetch: bool = True) -> dict[str, Any]:
    """Canonical remote-SHA packet used by G1/G2/G18."""
    fetched = fetch_origin(repo) if fetch else {"ok": True, "skipped": True}
    remote = ls_remote_main(repo)
    local = local_origin_main(repo)
    gh = github_main_sha()
    remote_sha = remote.get("sha") or ""
    gh_sha = gh.get("sha") or ""
    if gh.get("ok") and gh_sha and remote_sha and gh_sha != remote_sha:
        cross = False
    else:
        cross = True if (not gh.get("ok") or gh.get("skipped") or not gh_sha) else (gh_sha == remote_sha)
    klass = classify_main(repo, remote_sha)
    local_matches = bool(local) and bool(remote_sha) and local == remote_sha
    proven = bool(fetched.get("ok")) and bool(remote.get("ok")) and bool(remote_sha)
    return {
        "authority": AUTHORITY,
        "resolved_at": _now_iso(),
        "fetch": fetched,
        "remote_main_sha": remote_sha,
        "remote_ref_source": "git ls-remote origin refs/heads/main",
        "github_main_sha": gh_sha or None,
        "github_cross_check_ok": cross,
        "local_origin_main_sha": local,
        "local_matches_remote": local_matches,
        "ls_remote_ok": bool(remote.get("ok")),
        "fetch_ok": bool(fetched.get("ok")),
        "main_commit_class": klass.get("class"),
        "main_first_parent_sha": klass.get("first_parent"),
        "attested_runtime_content_sha": klass.get("attested_runtime_content_sha") or remote_sha,
        "attestation_sha": remote_sha if klass.get("class") == CLASS_ATTESTATION else None,
        "changed_files": klass.get("changed") or [],
        "pin_only": bool(klass.get("pin_only")),
        "proven": proven,
        "unproven_reason": (
            None if proven else (
                "fetch_failed" if not fetched.get("ok") else
                "ls_remote_failed" if not remote.get("ok") else
                "remote_sha_empty"
            )
        ),
    }


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    try:
        return _sha256_bytes(path.read_bytes())
    except Exception:
        return ""


def _git_bytes(repo: Path, *args: str, timeout: int = 40) -> tuple[int, bytes]:
    try:
        p = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            timeout=timeout,
        )
        return p.returncode, p.stdout or b""
    except Exception:
        return 1, b""


def blob_sha256_at(repo: Path, ref: str, relpath: str) -> str:
    """SHA-256 of the file bytes at ref:relpath (not the git blob id)."""
    if not ref or not relpath:
        return ""
    code, raw = _git_bytes(repo, "show", f"{ref}:{relpath}")
    if code != 0 or not raw:
        return ""
    return _sha256_bytes(raw)


def collect_evaluator_attestation(
    repo: Path,
    *,
    remote_truth: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Evidence packet for G0_CANONICAL_ACCEPTANCE_EVALUATOR.

    Required fields:
      acceptance_evaluator_commit_sha, git_branch, worktree_clean,
      untracked_count, evaluator_file_sha256, runner_file_sha256,
      remote_main_sha, main_commit_class, attested_runtime_content_sha,
      evaluator_diff_vs_remote_main
    """
    repo = Path(repo)
    truth = remote_truth or {}
    _code, head, _ = _run(["git", "-C", str(repo), "rev-parse", "HEAD"])
    _code, branch, _ = _run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"])
    _code, porcelain_all, _ = _run(
        ["git", "-C", str(repo), "status", "--porcelain", "-uall"],
    )
    all_lines = [ln for ln in (porcelain_all or "").splitlines() if ln.strip()]
    untracked_count = sum(1 for ln in all_lines if ln.startswith("??"))

    _code, porcelain_eval, _ = _run(
        ["git", "-C", str(repo), "status", "--porcelain", "-uall", "--",
         *ACCEPTANCE_EVALUATOR_FILES],
    )
    eval_lines = [ln for ln in (porcelain_eval or "").splitlines() if ln.strip()]
    evaluator_files_dirty = bool(eval_lines)
    untracked_evaluator_count = sum(1 for ln in eval_lines if ln.startswith("??"))
    # Pass condition: no dirty/untracked evaluator/runner files.
    worktree_clean = not evaluator_files_dirty

    ev_path = repo / ACCEPTANCE_EVALUATOR_RELPATH
    run_path = repo / ACCEPTANCE_RUNNER_RELPATH
    evaluator_file_sha256 = _sha256_file(ev_path)
    runner_file_sha256 = _sha256_file(run_path)

    remote = str(truth.get("remote_main_sha") or "").strip()
    content = str(truth.get("attested_runtime_content_sha") or "").strip()
    klass = str(truth.get("main_commit_class") or "") or CLASS_UNKNOWN

    disk_by_rel = {
        ACCEPTANCE_EVALUATOR_RELPATH: evaluator_file_sha256,
        ACCEPTANCE_RUNNER_RELPATH: runner_file_sha256,
    }
    diff_vs_remote: list[str] = []
    for rel, disk_sha in disk_by_rel.items():
        remote_sha = blob_sha256_at(repo, remote, rel) if remote else ""
        if not disk_sha or not remote_sha or disk_sha != remote_sha:
            diff_vs_remote.append(rel)

    match_content = bool(content)
    if content:
        for rel, disk_sha in disk_by_rel.items():
            parent_sha = blob_sha256_at(repo, content, rel)
            if not disk_sha or not parent_sha or disk_sha != parent_sha:
                match_content = False
                break

    proven = bool(
        truth.get("proven")
        and remote
        and head
        and evaluator_file_sha256
        and runner_file_sha256
    )
    return {
        "authority": AUTHORITY,
        "resolved_at": _now_iso(),
        "acceptance_evaluator_commit_sha": head,
        "git_branch": branch or "unknown",
        "worktree_clean": worktree_clean,
        "untracked_count": untracked_count,
        "evaluator_file_sha256": evaluator_file_sha256,
        "runner_file_sha256": runner_file_sha256,
        "remote_main_sha": remote,
        "main_commit_class": klass,
        "attested_runtime_content_sha": content,
        "evaluator_diff_vs_remote_main": diff_vs_remote,
        "evaluator_files_match_remote_main": not diff_vs_remote,
        "evaluator_files_match_attested_content": match_content,
        "evaluator_files_dirty": evaluator_files_dirty,
        "untracked_evaluator_count": untracked_evaluator_count,
        "full_worktree_clean": len(all_lines) == 0,
        "attestation_allowlist": sorted(ATTESTATION_ALLOWLIST_PATHS),
        "proven": proven,
        "unproven_reason": (
            None if proven else (
                "remote_sha_unproven" if not truth.get("proven") else
                "remote_main_sha_empty" if not remote else
                "head_empty" if not head else
                "evaluator_bytes_missing"
            )
        ),
    }


def live_matches_required_content(*, live_sha: str, truth: dict[str, Any]) -> tuple[bool, str]:
    """Attestation-only main requires live == content SHA, not the pin merge."""
    live = (live_sha or "").strip()
    remote = (truth.get("remote_main_sha") or "").strip()
    content = (truth.get("attested_runtime_content_sha") or "").strip()
    klass = truth.get("main_commit_class")
    if not truth.get("proven"):
        return False, "remote_sha_unproven"
    if not truth.get("local_matches_remote"):
        return False, "stale_local_origin_main"
    if klass == CLASS_ATTESTATION:
        if live and content and live == content:
            return True, "live_equals_attested_runtime_content"
        return False, "live_is_attestation_sha_not_content_sha"
    if klass == CLASS_RUNTIME:
        if live and remote and live == remote:
            return True, "live_equals_remote_main"
        return False, "live_lags_runtime_main"
    return False, "main_commit_class_unknown"
