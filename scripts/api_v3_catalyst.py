"""GET-only Command Center API for CatalystSymbolImpact@v1 (LQ-20261107-135).

The live route the operator surface calls:

  GET /api/v3/catalyst/symbol-impact?symbol=ANET&days=90&limit=25

READ_ONLY_ADVISORY. No broker/order/stop/risk/2FA mutation, no provider call, no financial action.
The wiring is three lines in api_v2.py's dispatcher (see the DONE note): this module exists so that
file only ever gains a prefix check, never a handler.
"""

from __future__ import annotations

from typing import Any

try:
    from lib import catalyst_impact_reader as R
except ImportError:  # pragma: no cover - script-path import (scripts/ on sys.path)
    from scripts.lib import catalyst_impact_reader as R  # type: ignore

AUTHORITY = R.AUTHORITY
SCHEMA = R.SCHEMA


def handle_get(path: str, query: dict | None = None) -> tuple[int, dict[str, Any]]:
    p = (path or "").strip("/")
    q = query if isinstance(query, dict) else {}

    if p in ("", "symbol-impact"):
        try:
            body = R.build(symbol=q.get("symbol"), days=q.get("days"), limit=q.get("limit"))
        except R.BadRequest as e:
            return 400, {"ok": False, "error": "bad_request", "detail": str(e), "schema": SCHEMA}
        except Exception as e:  # the DB is unreachable — say so, never answer with an empty list
            return 500, {"ok": False, "error": type(e).__name__, "detail": str(e)[:200], "schema": SCHEMA}
        return 200, body

    return 404, {
        "ok": False,
        "error": "not_found",
        "path": p,
        "schema": SCHEMA,
        "hint": "GET /api/v3/catalyst/symbol-impact?symbol=ANET&days=90&limit=25",
    }
