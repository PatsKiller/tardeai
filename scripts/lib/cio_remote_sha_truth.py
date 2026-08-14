"""Resolve remote Git SHA truth independently of a stale origin/main ref.

The acceptance runner must not award G1 because a local tracking ref is stale.
This module fetches, ls-remote's, and optionally cross-checks GitHub.

Authority: READ_ONLY_ADVISORY. No book mutation. No Telegram.
"""
from __future__ import annotations

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
