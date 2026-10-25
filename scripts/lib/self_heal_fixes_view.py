"""GET /api/v2/ops/self-heal-fixes — the self-heal fix log for Ops → Releases & schedules → Fixes. Read-only.

Operator 2026-10-25: "Arm the fixer and also a logger that tracks what was fixed". The writer is
scripts/self_heal_train_monitor.py (PR #2129): an append-only ``data/self_heal/fix_log.jsonl`` (SelfHealFixLog@v1,
one row per change of a fix) plus the heartbeat ``data/runtime/self-heal-train-monitor_last.json``. This module
projects the latest row per fix (newest first), a summary, and one fix's full event history for the detail sheet.

A missing log is UNAVAILABLE with its reason (the lane is not installed yet), never an empty green list. Stdlib only;
no DB, no subprocess, no send. MBI_BEHAVIOR = 0. AUTHORITY: READ_ONLY_ADVISORY.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA = "SelfHealFixes@v1"
LOG_SCHEMA = "SelfHealFixLog@v1"
FIX_LOG_REL = "data/self_heal/fix_log.jsonl"
HEARTBEAT_REL = "data/runtime/self-heal-train-monitor_last.json"
TAIL_LINES = 20000
MAX_LIMIT = 100
HEARTBEAT_STALE_S = 15 * 60
OPEN = ("remediating", "fix-PR-open", "fixer-queued", "fixed-released-pending")
FIXED = ("fixed-released", "fixed-no-release")
ESCALATED = ("escalated", "gave-up")
#: Fields the page shows; anything else in a row is not forwarded.
ROW_FIELDS = (
    "fix_id",
    "at",
    "event",
    "mode",
    "detected_at",
    "source",
    "kind",
    "signature",
    "title",
    "evidence_refs",
    "remediation_kind",
    "attempts",
    "model_cost_usd",
    "pr_number",
    "pr_head",
    "outcome",
    "released_sha",
    "verified_at",
    "detail",
)


def state_root(environ: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if environ is None else environ
    return Path(env.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def _rows(path: Path) -> tuple[list[dict], Optional[str]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]
    except FileNotFoundError:
        return [], "fix log not written yet: the self-heal-train-monitor lane is not installed"
    except OSError as exc:
        return [], f"fix log unreadable: {type(exc).__name__}"
    out = []
    for line in lines:
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("schema") == LOG_SCHEMA and doc.get("fix_id"):
            out.append({k: doc.get(k) for k in ROW_FIELDS})
    return out, None


def _age_s(value: Any, now: datetime) -> Optional[float]:
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return (now - t).total_seconds() if t.tzinfo else None


def payload(
    root: Path,
    *,
    now: Optional[datetime] = None,
    filter_: str = "all",
    offset: int = 0,
    limit: int = 50,
    fix_id: Optional[str] = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    rows, why = _rows(root / FIX_LOG_REL)
    latest: dict[str, dict] = {}
    for r in rows:
        latest[str(r["fix_id"])] = r
    fixes = sorted(latest.values(), key=lambda r: str(r.get("at") or ""), reverse=True)
    groups = {"open": OPEN, "fixed": FIXED, "escalated": ESCALATED}
    shown = [r for r in fixes if filter_ not in groups or r.get("outcome") in groups[filter_]]
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    hb: dict = {}
    try:
        hb = json.loads((root / HEARTBEAT_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        hb = {}
    hb_age = _age_s(hb.get("ok_at"), now)
    return {
        "schema": SCHEMA,
        "as_of": now.isoformat(),
        "status": "UNAVAILABLE" if why else "OK",
        "reason": why,
        "source": FIX_LOG_REL,
        "monitor": {
            "mode": hb.get("mode"),
            "ok_at": hb.get("ok_at"),
            "stale": hb_age is None or hb_age > HEARTBEAT_STALE_S,
            "policy_why": (hb.get("policy") or {}).get("why"),
            "ci": (hb.get("ci") or {}).get("ci"),
        },
        "summary": {
            "total": len(fixes),
            "open": sum(1 for r in fixes if r.get("outcome") in OPEN),
            "fixed": sum(1 for r in fixes if r.get("outcome") in FIXED),
            "escalated": sum(1 for r in fixes if r.get("outcome") in ESCALATED),
            "proposed": sum(1 for r in fixes if r.get("outcome") == "shadow-proposed"),
            "model_cost_usd": round(sum(float(r.get("model_cost_usd") or 0) for r in fixes), 2),
        },
        "rows": shown[offset : offset + limit],
        "total": len(shown),
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < len(shown),
        "history": [r for r in rows if r.get("fix_id") == fix_id][-100:] if fix_id else None,
    }


def handle(
    path: str, method: str, query: Optional[Mapping[str, Any]] = None, environ: Optional[Mapping[str, str]] = None
) -> tuple[int, dict]:
    """Route body for ``/api/v2/ops/self-heal-fixes`` (wired from scripts/api_v2.py)."""
    if method != "GET":
        return 405, {"ok": False, "error": "read_only"}
    q = dict(query or {})

    def one(key: str, default: Any = None) -> Any:
        v = q.get(key, default)
        return v[0] if isinstance(v, list) and v else v

    flt = str(one("filter", "all"))
    if flt not in ("all", "open", "fixed", "escalated"):
        return 400, {"ok": False, "error": "bad_filter"}
    try:
        offset, limit = int(one("offset", 0)), int(one("limit", 50))
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": "bad_paging"}
    fid = one("fix")
    return 200, {
        "ok": True,
        "data": payload(state_root(environ), filter_=flt, offset=offset, limit=limit, fix_id=str(fid) if fid else None),
    }
