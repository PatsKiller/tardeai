"""Priority requests for symbol-thesis acquisition (operator 2026-09-27).

Why: the options lifecycle's CIO said MORE_RESEARCH on DELL three times because DELL
had no house symbol thesis, but nothing asked the acquisition worker for one; it only
ran its own daily, debt-ordered list of 10. A MORE_RESEARCH decision on a symbol with
no thesis now files a request here. The acquisition runner and the curation monitor
serve open requests first. A request closes when acquisition publishes (or finds no
material change) after it, or when it ages out. Append-only; nothing is deleted.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

RELPATH = ("data", "cio", "symbol_thesis_priority_queue.jsonl")
LEDGER_RELPATH = ("data", "cio", "symbol_thesis_acquisition_ledger.jsonl")
DONE = {"PUBLISHED", "SYNTHESIZED_NO_MATERIAL_CHANGE"}
TTL_DAYS = 7


def _root(root: Any) -> Path:
    return Path(root) if root is not None else Path(__file__).resolve().parents[2]


def _rows(path: Path) -> list[dict[str, Any]]:
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
    except OSError:
        pass
    return out


def request(symbol: str, *, reason: str, source: str, root: Any = None,
            now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    row = {"schema": "SymbolThesisPriorityRequest@v1", "symbol": str(symbol).upper(), "reason": reason[:300],
           "source": source, "requested_at": now.isoformat(), "authority": "READ_ONLY_ADVISORY"}
    path = _root(root).joinpath(*RELPATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return row


def open_requests(root: Any = None, *, now: Optional[datetime] = None, ttl_days: float = TTL_DAYS) -> list[str]:
    """Symbols with an open request, oldest request first."""
    now = now or datetime.now(timezone.utc)
    base = _root(root)
    first: dict[str, str] = {}
    for r in _rows(base.joinpath(*RELPATH)):
        sym, at = str(r.get("symbol") or "").upper(), str(r.get("requested_at") or "")
        if not sym or not at:
            continue
        try:
            if datetime.fromisoformat(at) < now - timedelta(days=ttl_days):
                continue
        except ValueError:
            continue
        first.setdefault(sym, at)
        first[sym] = min(first[sym], at)
    if not first:
        return []
    done_at: dict[str, str] = {}
    for r in _rows(base.joinpath(*LEDGER_RELPATH)):
        sym = str(r.get("symbol") or "").upper()
        if sym in first and r.get("status") in DONE:
            done_at[sym] = max(done_at.get(sym, ""), str(r.get("as_of") or ""))
    return [s for s, at in sorted(first.items(), key=lambda kv: kv[1]) if done_at.get(s, "") < at]
