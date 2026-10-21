"""data_plausibility_view.py — GET /api/v2/system/data-plausibility (audit 2026-10-21).

Serves the latest scripts/data_plausibility_monitor.py run receipt
(``<state_root>/data/runtime/data_plausibility_last_run.json``): checked / violations / blocking and one row per
rule. Reads one file; computes nothing about the data and never connects to a database.

A missing or unreadable receipt is ``NO_RECEIPT`` / ``UNAVAILABLE`` — never an empty green. A receipt older than
``STALE_AFTER_H`` is ``STALE`` (the monitor runs on a timer; a stopped timer must not look clean).

AUTHORITY: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

SCHEMA = "DataPlausibilityView@v1"
RECEIPT_REL = Path("data") / "runtime" / "data_plausibility_last_run.json"
STALE_AFTER_H = 26.0


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _count(v: Any) -> Optional[int]:
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def build_view(doc: Optional[dict], *, now: datetime, path: str = "", error: Optional[str] = None) -> dict[str, Any]:
    """Pure: receipt dict (or None) → view."""
    base: dict[str, Any] = {"schema": SCHEMA, "authority": "READ_ONLY_ADVISORY", "as_of": now.isoformat(),
                            "receipt_path": path, "ran_at": None, "age_h": None, "stale_after_h": STALE_AFTER_H,
                            "checked": None, "violations": None, "blocking": None, "blocking_items": [],
                            "rules": None, "note": None}
    if doc is None:
        base.update(status="NO_RECEIPT" if error is None else "UNAVAILABLE",
                    note=error or "data_plausibility_monitor.py has not written a run receipt here")
        return base
    if not isinstance(doc, dict):
        base.update(status="UNAVAILABLE", note="receipt is not a JSON object")
        return base
    ran = _parse(doc.get("ran_at"))
    age_h = round((now - ran).total_seconds() / 3600.0, 2) if ran else None
    checked = _count(doc.get("checked"))
    blocking = _count(doc.get("blocking"))
    if blocking is None:
        blocking = _count(doc.get("off"))     # receipts before 2026-10-21 name the blocking count `off`
    items = [str(x) for x in (doc.get("blocking_items") or []) if x]
    rules = doc.get("results")
    rows = None
    if isinstance(rules, list):
        rows = [{"table": r.get("table"), "column": r.get("column"), "status": r.get("status"),
                 "severity": r.get("severity"), "violations": r.get("violations"), "total": r.get("total"),
                 "detail": r.get("detail")} for r in rules if isinstance(r, dict)]
        rows.sort(key=lambda r: (r["status"] != "VIOLATION", r["severity"] != "BLOCK", str(r["table"]), str(r["column"])))
    violations = _count(doc.get("violations"))
    if violations is None and rows is not None:
        violations = sum(1 for r in rows if r["status"] == "VIOLATION")
    if checked is None or blocking is None or ran is None:
        status = "UNAVAILABLE"
        note = "receipt is missing checked / blocking / ran_at"
    elif age_h is not None and age_h > STALE_AFTER_H:
        status, note = "STALE", f"last run {age_h} h ago (> {STALE_AFTER_H} h)"
    elif blocking > 0:
        status, note = "BLOCK", None
    else:
        status, note = "OK", None
    if rows is None and note is None:
        note = "receipt predates per-rule rows (monitor before 2026-10-21); counts only"
    base.update(status=status, ran_at=ran.isoformat() if ran else None, age_h=age_h, checked=checked,
                violations=violations, blocking=blocking, blocking_items=items, rules=rows, note=note)
    return base


def load_view(root: Path | str, *, now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    path = Path(root) / RECEIPT_REL
    if not path.is_file():
        return build_view(None, now=now, path=str(path))
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return build_view(None, now=now, path=str(path), error=f"{type(exc).__name__}: {str(exc)[:120]}")
    return build_view(doc, now=now, path=str(path))
