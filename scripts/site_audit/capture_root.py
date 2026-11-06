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



def assert_leaf_inside_root(path: Path | str, root: Path | str) -> Path:
    """Return the leaf path, or refuse when writing it could land outside the capture root.

    cx-openai-4 R2 on #2648: the per-page DIRECTORY is resolved and checked, but a leaf inside it can itself be a
    pre-existing symlink — ``<vp>.txt -> ../../repo/apps/...`` — and ``write_text``/``screenshot`` follow it, so a
    capture walked into the checkout through a file name. Only refusing the directory was half the guarantee.

    A leaf that exists as a symlink is refused (there is no legitimate reason for one in a capture directory); a
    leaf whose PARENT resolves outside the root is refused too. The parent is the thing that can be a symlink
    chain — the leaf itself does not exist yet in the normal case.
    """
    leaf = Path(path).expanduser()
    base = Path(root).expanduser().resolve()
    if leaf.is_symlink():
        raise CaptureRootRefused(f"capture leaf {leaf} is a symlink; refusing to write through it")
    parent = leaf.parent.resolve()
    if parent != base and base not in parent.parents:
        raise CaptureRootRefused(f"capture leaf {leaf} is outside the capture root {base}")
    return leaf

def looks_like_capture(path: Path | str) -> bool:
    text = str(path)
    return any(hint in text for hint in IN_REPO_CAPTURE_HINTS)


def configured_capture_root(*, repo_root: Path | str) -> Path:
    """The root named by the lane's environment, refused if unset or inside the checkout."""
    raw = os.getenv(CAPTURE_ROOT_ENV, "").strip()
    if not raw:
        raise CaptureRootRefused(f"{CAPTURE_ROOT_ENV} is not set: the capture root is configuration, not code")
    return assert_capture_root(raw, repo_root=repo_root)


def assert_inside_root(path: Path | str, root: Path | str) -> Path:
    """Return the resolved path, or refuse when it left the capture root.

    The root check alone is not enough (codex R1, 2026-11-04): a per-page directory can already exist as a symlink
    whose target is inside the checkout, and `--out` used to skip the root check entirely. Both are refused here, on
    the RESOLVED path, so a symlinked descendant cannot smuggle a capture into the repository.
    """
    resolved = Path(path).expanduser().resolve()
    base = Path(root).expanduser().resolve()
    if resolved != base and base not in resolved.parents:
        raise CaptureRootRefused(f"capture path {resolved} is outside the capture root {base}")
    return resolved
