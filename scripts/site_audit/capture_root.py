"""Captures never enter the repo. Structural, not a note in a doc.

The repo is public and a capture holds real values (prices, positions, names). A capture root inside the checkout is
refused here, the ignore rules exist for accidental in-repo roots, and a test asserts both.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The capture root is CONFIGURATION, not code: the checkout is public, and a personal path is identifying data.
#: It is supplied by the lane (SITE_AUDIT_CAPTURE_ROOT) and must resolve outside the repository.
CAPTURE_ROOT_ENV = "SITE_AUDIT_CAPTURE_ROOT"

#: Names an in-repo capture directory can take; .gitignore carries the same patterns.
IN_REPO_CAPTURE_HINTS = ("page-audit-", "site-audit-capture", "audit-captures")


class CaptureRootRefused(ValueError):
    pass


def assert_capture_root(path: Path | str, *, repo_root: Path | str) -> Path:
    """Return the resolved capture root, or refuse when it would live inside the checkout."""
    resolved = Path(path).expanduser().resolve()
    repo = Path(repo_root).expanduser().resolve()
    if resolved == repo or repo in resolved.parents:
        raise CaptureRootRefused(f"capture root {resolved} is inside the repository {repo}")
    if any(hint in str(resolved) for hint in IN_REPO_CAPTURE_HINTS) and repo in resolved.parents:
        raise CaptureRootRefused(f"capture root {resolved} is an in-repo capture directory")
    return resolved


def looks_like_capture(path: Path | str) -> bool:
    text = str(path)
    return any(hint in text for hint in IN_REPO_CAPTURE_HINTS)


def configured_capture_root(*, repo_root: Path | str) -> Path:
    """The root named by the lane's environment, refused if unset or inside the checkout."""
    raw = os.getenv(CAPTURE_ROOT_ENV, "").strip()
    if not raw:
        raise CaptureRootRefused(f"{CAPTURE_ROOT_ENV} is not set: the capture root is configuration, not code")
    return assert_capture_root(raw, repo_root=repo_root)
