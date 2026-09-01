"""Read-only peek at the operator's git-push grant in the Cursor approval ledger.

When the operator runs ``bin/guard grant git-push``, the same ledger entry
authorizes both the Cursor shell guard (which consumes one use per push) and
the git pre-push hook (peek only — no second consume).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _import_guard_ledger():
    hooks = _REPO_ROOT / ".cursor" / "hooks"
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import guard_ledger as gl  # noqa: WPS433

    return gl


def approvals_dir() -> Path:
    return Path(os.environ.get("GUARD_APPROVALS_DIR", Path.home() / ".cursor" / "approvals"))


def git_push_grant_active(*, adir: Path | None = None) -> dict[str, Any] | None:
    """Return the active git-push grant record, or None."""
    gl = _import_guard_ledger()
    target = adir or approvals_dir()
    try:
        listed = gl.ledger_list(target)
    except Exception:
        return None
    if listed.get("state") not in {gl.VALID_EMPTY, gl.VALID_NONEMPTY}:
        return None
    rec = (listed.get("active") or {}).get("git-push")
    return rec if isinstance(rec, dict) else None


def push_authorized_by_guard(*, adir: Path | None = None) -> tuple[bool, str]:
    rec = git_push_grant_active(adir=adir)
    if not rec:
        return False, ""
    return True, str(rec.get("reason") or "guard git-push grant")
