"""Persistent staged trade ideas for Research Intelligence desk (v3).

JSON SSOT: data/portfolios/state/ri_staged_ideas.json
No DB migration required — survives reloads; operator can stage from cards.

v3 lifecycle: staged → watchlisted | directive_created | proposed_paper |
dismissed | expired (14d default). Promotions are operator-clicked only and
run through EXISTING pathways (directive create, PENDING paper proposal) —
this module never talks to a broker surface.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "ri_staged_ideas.json"

STATUSES = ("staged", "watchlisted", "directive_created", "proposed_paper", "dismissed", "expired")
EXPIRY_DAYS_DEFAULT = 14
# Statuses still awaiting an operator decision — only these auto-expire
_EXPIRABLE = ("staged",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expire_pass(doc: dict[str, Any]) -> bool:
    """Lazy expiry on read: undecided ideas past expires_at flip to 'expired'
    (still listed — the Expired fold shows them; nothing is deleted)."""
    changed = False
    now = datetime.now(timezone.utc)
    for idea in doc.get("ideas") or []:
        if idea.get("status") not in _EXPIRABLE or idea.get("dismissed"):
            continue
        exp = idea.get("expires_at")
        if not exp:
            continue
        try:
            exp_dt = datetime.fromisoformat(str(exp))
        except ValueError:
            continue
        if exp_dt.tzinfo is None:
            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
        if exp_dt < now:
            idea["status"] = "expired"
            idea["updated_at"] = _now()
            changed = True
    return changed


def _load() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"version": 1, "ideas": [], "updated_at": None}
    try:
        d = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(d, dict):
            return {"version": 1, "ideas": [], "updated_at": None}
        d.setdefault("ideas", [])
        return d
    except Exception:
        return {"version": 1, "ideas": [], "updated_at": None}


def _save(doc: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    doc["updated_at"] = _now()
    doc["version"] = 1
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    tmp.replace(STATE_PATH)


def list_staged(*, include_dismissed: bool = False, limit: int = 50) -> dict[str, Any]:
    doc = _load()
    if _expire_pass(doc):
        _save(doc)
    ideas = list(doc.get("ideas") or [])
    if not include_dismissed:
        ideas = [i for i in ideas if not i.get("dismissed")]
    ideas.sort(key=lambda x: str(x.get("staged_at") or ""), reverse=True)
    by_status: dict[str, int] = {}
    for i in ideas:
        s = i.get("status") or "staged"
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "ok": True,
        "count": len(ideas[:limit]),
        "ideas": ideas[:limit],
        "by_status": by_status,
        "updated_at": doc.get("updated_at"),
        "path": str(STATE_PATH.relative_to(PROJECT_ROOT)),
    }


def get_idea(idea_id: str) -> dict[str, Any] | None:
    for idea in _load().get("ideas") or []:
        if idea.get("id") == idea_id:
            return idea
    return None


def stage_idea(body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create or refresh a staged idea from a research card ticker."""
    b = body or {}
    symbol = str(b.get("symbol") or "").upper().strip()
    if not symbol or not symbol.isalnum() or len(symbol) > 8:
        return {"ok": False, "error": "valid symbol required"}

    # Incomplete data cannot be staged as trade
    if b.get("data_complete") is False or b.get("allow_stage") is False:
        return {
            "ok": False,
            "error": "incomplete_data",
            "detail": b.get("incomplete_reason")
            or "Missing RSI/RS or critical fields — use Watchlist, not Stage Trade.",
        }

    # v3 (E3): a staged idea without an exit note is not a plan. The note must
    # come from the caller — no silent boilerplate default.
    stop_note = str(b.get("provisional_stop_note") or b.get("stop_note") or "").strip()
    if not stop_note:
        return {
            "ok": False,
            "error": "stop_note_required",
            "detail": "Provide an exit/stop note (where protection goes and why) before staging.",
        }

    side = str(b.get("side") or "buy").lower()
    if side not in ("buy", "sell", "trim", "protect"):
        side = "buy"
    role = str(b.get("role") or "add_candidate")
    if role == "trim_candidate":
        side = "sell"
    if role == "protect":
        side = "protect"

    idea = {
        "id": str(b.get("id") or f"ri-{symbol.lower()}-{uuid.uuid4().hex[:10]}"),
        "symbol": symbol,
        "side": side,
        "role": role,
        "status": "staged",
        "dismissed": False,
        "source_item_id": b.get("source_item_id"),
        "source_title": (b.get("source_title") or "")[:200],
        "primary_category": b.get("primary_category"),
        "suggested_weight_pct": b.get("suggested_weight_pct"),
        "size_min_pct": b.get("size_min_pct"),
        "size_max_pct": b.get("size_max_pct"),
        "dollar_lo": b.get("dollar_lo"),
        "dollar_hi": b.get("dollar_hi"),
        "funding_source": b.get("funding_source") or b.get("funding"),
        "require_funding_trim": bool(b.get("require_funding_trim")),
        "funding_symbol": b.get("funding_symbol") or ("SCHG" if b.get("require_funding_trim") else None),
        "conviction_tier": b.get("conviction_tier"),
        "conviction_score": b.get("conviction_score"),
        "provisional_stop_note": stop_note[:400],
        "sizing_reason": (b.get("sizing_reason") or "")[:500],
        "rationale": (b.get("rationale") or b.get("why_selected") or "")[:400],
        "related_themes": b.get("related_themes") if isinstance(b.get("related_themes"), list) else [],
        "staged_at": _now(),
        "created_at": _now(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=EXPIRY_DAYS_DEFAULT)).isoformat(),
        "updated_at": _now(),
        "meta": b.get("meta") if isinstance(b.get("meta"), dict) else {},
    }

    doc = _load()
    ideas = [i for i in (doc.get("ideas") or []) if not (
        str(i.get("symbol") or "").upper() == symbol
        and not i.get("dismissed")
        and str(i.get("side")) == side
    )]
    ideas.insert(0, idea)
    doc["ideas"] = ideas[:80]
    _save(doc)
    return {
        "ok": True,
        "idea": idea,
        "message": f"Staged {symbol} ({side}) — review in Staged Ideas on Research Intelligence.",
        "count": len([i for i in doc["ideas"] if not i.get("dismissed")]),
    }


def update_staged(idea_id: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    b = body or {}
    doc = _load()
    ideas = list(doc.get("ideas") or [])
    found = None
    for i, idea in enumerate(ideas):
        if idea.get("id") == idea_id:
            if b.get("dismissed") is not None:
                idea["dismissed"] = bool(b.get("dismissed"))
                if idea["dismissed"]:
                    idea["status"] = "dismissed"
            if b.get("status"):
                idea["status"] = str(b.get("status"))[:40]
            if b.get("suggested_weight_pct") is not None:
                idea["suggested_weight_pct"] = b.get("suggested_weight_pct")
            if b.get("funding_source") is not None:
                idea["funding_source"] = b.get("funding_source")
            if b.get("note") is not None:
                idea["operator_note"] = str(b.get("note"))[:500]
            idea["updated_at"] = _now()
            ideas[i] = idea
            found = idea
            break
    if not found:
        return {"ok": False, "error": "idea_not_found"}
    doc["ideas"] = ideas
    _save(doc)
    return {"ok": True, "idea": found}


def dismiss_idea(idea_id: str) -> dict[str, Any]:
    return update_staged(idea_id, {"dismissed": True, "status": "dismissed"})
