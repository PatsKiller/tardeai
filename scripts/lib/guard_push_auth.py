"""Read-only peek at the operator's git-push grant in the Cursor approval ledger.

When the operator runs ``bin/guard grant git-push``, the same ledger entry
authorizes both the Cursor shell guard (which consumes one use per push) and
the git pre-push hook (peek only — no second consume).
"""

from __future__ import annotations

import os
import re
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


# ---------------------------------------------------------------------------
# Scope binding (AGENTS.md 1.3.0 PROPOSED; review 2026-09-25 finding).
#
# Any active git-push grant used to authorize a push -- and override the push
# budget -- for ANY branch: a 100-use campaign grant covered unrelated branches.
# A grant is bounded permission for one operation, so its reason must name what
# it covers: the branch being pushed or its head SHA (>= 7 hex chars).
#
# Default: WARN only, so existing sessions keep working while the operator
# decides. TRADEAI_GUARD_PUSH_SCOPE_ENFORCE=1 makes an unscoped grant refuse.
SCOPE_ENFORCE_ENV = "TRADEAI_GUARD_PUSH_SCOPE_ENFORCE"
_SHA_TOKEN = re.compile(r"\b[0-9a-f]{7,40}\b")


def grant_scope_covers(reason: str, *, branch: str, head_sha: str) -> tuple[bool, str]:
    """Does this grant's reason name ``branch`` or a prefix of ``head_sha``? Pure."""
    text = str(reason or "")
    b = str(branch or "").strip()
    if b.startswith("refs/heads/"):
        b = b[len("refs/heads/") :]
    if b and b != "HEAD" and b in text:
        return True, "grant names this branch"
    sha = str(head_sha or "").strip().lower()
    if sha:
        for tok in _SHA_TOKEN.findall(text.lower()):
            if sha.startswith(tok):
                return True, "grant names this head SHA"
    return False, "grant reason names neither this branch nor this head SHA"


def scope_enforced() -> bool:
    return os.environ.get(SCOPE_ENFORCE_ENV, "") == "1"


def push_authorized_by_guard_scoped(*, branch: str, head_sha: str, adir: Path | None = None) -> dict[str, Any]:
    """Guard authorization for one push, with the scope verdict.

    ``ok`` is what the pre-push hook acts on. ``scoped`` says whether the grant
    names this push. Unscoped grants still authorize unless enforcement is on,
    and the hook warns either way."""
    rec = git_push_grant_active(adir=adir)
    if not rec:
        return {
            "ok": False,
            "scoped": False,
            "enforced": scope_enforced(),
            "why": "no active git-push grant",
            "reason": "",
        }
    reason = str(rec.get("reason") or "guard git-push grant")
    covers, why = grant_scope_covers(reason, branch=branch, head_sha=head_sha)
    enforced = scope_enforced()
    return {"ok": covers or not enforced, "scoped": covers, "enforced": enforced, "why": why, "reason": reason}
