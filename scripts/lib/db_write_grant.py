"""Verify an operator ``db-write`` grant id against the guard ledger (read-only peek).

A destructive DB tool's ``--apply`` names the grant it runs under in ``TRADEAI_DB_WRITE_GRANT``. This
module checks that id against the ACTIVE ``db-write`` record of the guard ledger
(``.cursor/hooks/guard_ledger.py``; ``$GUARD_APPROVALS_DIR`` or ``~/.cursor/approvals``), the same
read-only ``ledger_list`` peek ``scripts/lib/guard_push_auth.py`` uses for ``git-push``. It never
issues, consumes or revokes: the guard hook already accounts for the command that launched the
tool. The verdict is written into the tool's receipt so the durable artifact names its authority.

Accepted id: the grant's 32-hex ``grant_id`` or a prefix of at least 12 hex chars (operators quote
16, e.g. ``c45f5cc126cd1d7c``). Refused: unset, malformed, ledger missing/corrupt, no active
db-write grant (expired or used up), or an id that is not the active grant's.

AUTHORITY: READ_ONLY_ADVISORY. No credential is read.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = "DbWriteGrantCheck@v1"
ENV = "TRADEAI_DB_WRITE_GRANT"
TIER = "db-write"
MIN_ID_HEX = 12
_ID_RE = re.compile(r"^[0-9a-f]{%d,64}$" % MIN_ID_HEX)
_REPO = Path(__file__).resolve().parents[2]


def _guard_ledger():
    hooks = _REPO / ".cursor" / "hooks"
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import guard_ledger as gl  # noqa: WPS433

    return gl


def approvals_dir() -> Path:
    return Path(os.environ.get("GUARD_APPROVALS_DIR") or (Path.home() / ".cursor" / "approvals"))


def verify(grant_id: Optional[str], *, adir: Optional[Path] = None, now: Optional[int] = None) -> dict[str, Any]:
    supplied = (grant_id or "").strip().lower()
    out: dict[str, Any] = {"schema": SCHEMA, "tier": TIER, "env": ENV, "grant_id_supplied": supplied or None,
                           "ok": False, "checked_at": int(time.time() if now is None else now)}
    if not supplied:
        out["reason"] = f"{ENV} is not set: --apply needs the operator's db-write grant id"
        return out
    if not _ID_RE.match(supplied):
        out["reason"] = f"{ENV} is not a grant id (hex, >= {MIN_ID_HEX} chars)"
        return out
    try:
        gl = _guard_ledger()
        listed = gl.ledger_list(adir or approvals_dir(), now=now)
    except Exception as exc:  # noqa: BLE001 — a ledger that cannot be read authorizes nothing
        out["reason"] = f"guard ledger unreadable: {type(exc).__name__}: {str(exc)[:120]}"
        return out
    if listed.get("state") not in {gl.VALID_EMPTY, gl.VALID_NONEMPTY}:
        out["reason"] = f"guard ledger state {listed.get('state')}"
        return out
    rec = (listed.get("active") or {}).get(TIER)
    if not isinstance(rec, dict):
        out["reason"] = "no active db-write grant (never issued, expired, or uses exhausted)"
        return out
    full = str(rec.get("grant_id") or "").lower()
    if not full or not full.startswith(supplied):
        out["reason"] = "grant id does not match the active db-write grant"
        return out
    out.update(ok=True, reason="active db-write grant", grant_id=full, expires=int(rec.get("expires") or 0),
               uses=rec.get("uses"), grant_reason=str(rec.get("reason") or "")[:300])
    return out
