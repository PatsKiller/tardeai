"""G0 — acceptance evaluator self-attestation.

The auditor may not award CORE_CIO_PRODUCTION_ACCEPTANCE while running
unmerged, dirty, or monkey-patched evaluator code.

Authority: READ_ONLY_ADVISORY. No network writes.
"""
from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
EVALUATOR_FILES = (
    "scripts/lib/cio_acceptance_v4.py",
    "scripts/run_cio_acceptance.py",
)
ATTESTATION_ONLY_PATHS = frozenset({
    "docs/investment-office/RELEASE_MANIFEST.md",
    "docs/investment-office/RELEASE_MANIFEST.json",
    "docs/investment-office/CIO_FINAL_ACCEPTANCE_CLOSURE_BASELINE.md",
})


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(args: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode == 0:
            return (r.stdout or "").strip()
    except Exception:
        pass
    return ""


def collect_evaluator_attestation(
    *,
    repo: Path,
    remote_main_sha: str = "",
    main_commit_class: str = "",
    attested_runtime_content_sha: str = "",
) -> dict[str, Any]:
    """Read-only git/worktree proof of which evaluator produced the run."""
    repo = Path(repo)
    head = _git(["rev-parse", "HEAD"], repo)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    status = _git(["status", "--porcelain"], repo)
    dirty_lines = [ln for ln in status.splitlines() if ln.strip()]
    untracked = [ln[3:] for ln in dirty_lines if ln.startswith("??")]
    changed = [ln[3:] for ln in dirty_lines if not ln.startswith("??")]
    hashes = {
        rel: file_sha256(repo / rel) for rel in EVALUATOR_FILES
    }
    remote_hashes = {}
    content_hashes = {}
    if remote_main_sha:
        for rel in EVALUATOR_FILES:
            blob = _git(["show", f"{remote_main_sha}:{rel}"], repo)
            remote_hashes[rel] = hashlib.sha256(blob.encode("utf-8")).hexdigest() if blob else ""
    if attested_runtime_content_sha:
        for rel in EVALUATOR_FILES:
            blob = _git(["show", f"{attested_runtime_content_sha}:{rel}"], repo)
            content_hashes[rel] = hashlib.sha256(blob.encode("utf-8")).hexdigest() if blob else ""
    vs_main = []
    vs_content = []
    for rel in EVALUATOR_FILES:
        if remote_hashes.get(rel) and hashes.get(rel) != remote_hashes.get(rel):
            vs_main.append(rel)
        if content_hashes.get(rel) and hashes.get(rel) != content_hashes.get(rel):
            vs_content.append(rel)
    return {
        "authority": AUTHORITY,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "acceptance_evaluator_commit_sha": head,
        "acceptance_evaluator_git_branch": branch,
        "acceptance_evaluator_worktree_clean": len(dirty_lines) == 0,
        "acceptance_evaluator_untracked_count": len(untracked),
        "acceptance_evaluator_changed_files": changed,
        "acceptance_evaluator_untracked_files": untracked,
        "acceptance_evaluator_file_sha256": hashes.get("scripts/lib/cio_acceptance_v4.py", ""),
        "acceptance_runner_file_sha256": hashes.get("scripts/run_cio_acceptance.py", ""),
        "evaluator_file_hashes": hashes,
        "remote_main_sha": remote_main_sha,
        "main_commit_class": main_commit_class,
        "attested_runtime_content_sha": attested_runtime_content_sha,
        "remote_main_evaluator_hashes": remote_hashes,
        "content_evaluator_hashes": content_hashes,
        "evaluator_diff_vs_remote_main": vs_main,
        "evaluator_diff_vs_runtime_content": vs_content,
        "allowed_attestation_only_diff": sorted(ATTESTATION_ONLY_PATHS),
    }


def passing_attestation_snapshot(
    *,
    head_sha: str,
    remote_main_sha: str,
    main_commit_class: str = "RUNTIME_CONTENT",
    attested_runtime_content_sha: str = "",
    worktree_clean: bool = True,
    untracked_count: int = 0,
    evaluator_sha: str = "e" * 64,
    runner_sha: str = "r" * 64,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Test helper — a complete G0 evidence dict (does not touch git)."""
    rec = {
        "acceptance_evaluator_commit_sha": head_sha,
        "acceptance_evaluator_git_branch": "main",
        "acceptance_evaluator_worktree_clean": worktree_clean,
        "acceptance_evaluator_untracked_count": untracked_count,
        "acceptance_evaluator_file_sha256": evaluator_sha,
        "acceptance_runner_file_sha256": runner_sha,
        "remote_main_sha": remote_main_sha,
        "main_commit_class": main_commit_class,
        "attested_runtime_content_sha": attested_runtime_content_sha or head_sha,
        "evaluator_diff_vs_remote_main": [],
        "evaluator_diff_vs_runtime_content": [],
        "remote_main_evaluator_hashes": {"scripts/lib/cio_acceptance_v4.py": evaluator_sha},
        "content_evaluator_hashes": {"scripts/lib/cio_acceptance_v4.py": evaluator_sha},
    }
    if extra:
        rec.update(extra)
    return rec
