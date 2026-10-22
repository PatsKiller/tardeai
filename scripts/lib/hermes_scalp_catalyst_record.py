"""Pick one symbol's Hermes scalp-catalyst research record from a day file (pure; 2026-10-22, Gate 1).

The store is ``data/hermes/momentum_catalysts/<day>_catalysts.jsonl`` (single writer
``hermes_momentum_catalyst_researcher.py --source scalp``; location: lib/hermes_catalyst_store.py). Two readers
must pick the same record the same way:

- ``lib.data_broker.scalp_list.get_scalp_catalyst`` — the Active Trader alert's ``catalyst_line`` fallback;
- ``lib.scanner_candidate_projection`` — the Shared Momentum projection's AT catalyst fallback.

Stdlib only (json, datetime). No environment read, no file I/O, no network, no write: the caller reads the lines.
READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

NO_CLEAR_CATALYST = "no_clear_catalyst"


def _research_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif not value:
        return None
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    # naive = host-local, as lib.data_broker.scalp_list._utc reads it (the writers stamp datetime.now())
    return (dt if dt.tzinfo else dt.astimezone()).astimezone(timezone.utc)


def select_scalp_catalyst(symbol: str, lines: Iterable[str]) -> dict[str, Any] | None:
    """The newest research record for ``symbol`` (ties: the later line). None when the symbol is absent; else
    status FOUND | NONE_FOUND with catalyst_type, summary, confidence, source_count, researched_at, source."""
    sym = str(symbol or "").strip().upper()
    best: dict[str, Any] | None = None
    best_ts: datetime | None = None
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or str(rec.get("symbol") or "").upper() != sym:
            continue
        ts = _research_ts(rec.get("research_timestamp"))
        if best is None or (ts is not None and (best_ts is None or ts >= best_ts)):
            best, best_ts = rec, ts
    if best is None:
        return None
    ctype = str(best.get("catalyst_type") or "").strip() or NO_CLEAR_CATALYST
    return {
        "status": "NONE_FOUND" if ctype == NO_CLEAR_CATALYST else "FOUND",
        "catalyst_type": ctype,
        "summary": str(best.get("catalyst_summary") or "").strip() or None,
        "confidence": best.get("confidence"),
        "source_count": best.get("source_count"),
        "researched_at": best.get("research_timestamp"),
        "source": "hermes_momentum_catalyst_researcher",
    }
