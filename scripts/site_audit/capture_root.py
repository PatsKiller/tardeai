"""Captures never enter the repo. Structural, not a note in a doc.

The repo is public and a capture holds real values (prices, positions, names). A capture root inside the checkout is
refused here, the ignore rules exist for accidental in-repo roots, and a test asserts both.
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_CAPTURE_ROOT = Path("/home/johnclaw/trade-ai-releases/persistent-state/data/audit")

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
