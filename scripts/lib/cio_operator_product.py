"""CIOOperatorProduct@v1 — one operator-facing product, many renderers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.canonical_store_registry import load_json_store, resolve_store

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOOperatorProduct@v1"
UNAVAILABLE_REASONS = (
    "PRODUCER_NOT_RUN",
    "STALE",
    "WRONG_SOURCE_PIN",
    "INELIGIBLE",
    "DATA_CONFLICT",
    "MISSING_DEPENDENCY",
)
ACTIONS = ("HOLD", "WATCH", "REVIEW", "TRIM", "REENTER", "AVOID", "NO_ACTION", "HOLD_CASH")
WHEN = ("NOW", "TODAY", "NEXT_SESSION", "WATCH_ONLY", "NOTHING")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _map_action(raw: str) -> str:
    a = str(raw or "").upper().replace(" ", "_")
    aliases = {
        "RE_ENTER": "REENTER", "HOLD_POSTURE": "HOLD", "WAIT": "WATCH",
        "DO_NOW": "REVIEW", "WATCH_CLOSELY": "WATCH",
    }
    a = aliases.get(a, a)
    return a if a in ACTIONS else "REVIEW"


def _entry_from_rec(row: dict[str, Any]) -> dict[str, Any]:
    action = _map_action(row.get("recommended_action") or row.get("action") or row.get("title"))
    when = "NOW" if str(row.get("priority") or "").upper() == "HIGH" else "NEXT_SESSION"
    if action in {"HOLD", "HOLD_CASH", "NO_ACTION"}:
        when = "NOTHING"
    if action in {"WATCH"}:
        when = "WATCH_ONLY"
    return {
        "what_changed": row.get("title") or row.get("action") or "CIO observation",
        "why_it_matters": row.get("description") or row.get("rationale") or "",
        "cio_decision": action,
        "what_should_i_do": when,
        "why": row.get("rationale") or row.get("description") or "",
        "confidence": row.get("confidence"),
        "counter_evidence": row.get("counter") or row.get("counterpoint"),
        "data_quality": row.get("data_quality") or "OK",
        "blockers": row.get("blockers") or [],
        "next_review": row.get("next_review"),
        "source": "cio.product.current",
        "symbol": row.get("symbol"),
        "authority": AUTHORITY,
        "financial_action": False,
    }


def unavailable(*, reason: str, detail: str | None = None, path: str | None = None) -> dict[str, Any]:
    r = reason if reason in UNAVAILABLE_REASONS else "PRODUCER_NOT_RUN"
    return {
        "schema": SCHEMA,
        "available": False,
        "reason": r,
        "detail": detail,
        "path": path,
        "entries": [],
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "note": "Never use ambiguous available=false without reason.",
    }


def build_operator_product(*, root: Path | str | None = None, persist: bool = False) -> dict[str, Any]:
    loc = load_json_store("cio.product.current", root=root)
    if not loc.get("available"):
        reason = "PRODUCER_NOT_RUN"
        if loc.get("reason") == "INVALID_SCHEMA":
            reason = "DATA_CONFLICT"
        return unavailable(reason=reason, detail=str(loc.get("reason")), path=loc.get("path"))
    brief = loc["data"] if isinstance(loc.get("data"), dict) else {}
    recs = list(brief.get("recommendations") or [])
    entries = [_entry_from_rec(r) for r in recs if isinstance(r, dict)]
    if not entries:
        summary = brief.get("summary")
        if isinstance(summary, dict):
            entries.append(_entry_from_rec({
                "title": summary.get("headline") or "CIO posture",
                "description": summary.get("narrative") or json.dumps(summary, default=str)[:240],
                "recommended_action": brief.get("final_position") or "HOLD",
            }))
        elif summary:
            entries.append(_entry_from_rec({"title": "CIO posture", "description": str(summary), "recommended_action": "HOLD"}))
    product = {
        "schema": SCHEMA,
        "available": True,
        "reason": None,
        "as_of": brief.get("as_of") or _now(),
        "source_store": "cio.product.current",
        "source_path": loc.get("path"),
        "entries": entries[:20],
        "competing_products": ["morning_command", "trade_ai_brief", "aegis_evening"],
        "canonical": True,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "gui_is_projection": True,
    }
    if persist:
        out = resolve_store("cio.operator_product.current", root=root)
        path = Path(out["primary_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(product, indent=2, default=str) + "\n", encoding="utf-8")
        product["persisted_path"] = str(path)
    return product


def render_human(product: dict[str, Any]) -> str:
    if not product.get("available"):
        return (
            f"CIO_PRODUCT_UNAVAILABLE\n"
            f"reason: {product.get('reason')}\n"
            f"{product.get('detail') or ''}"
        ).strip()
    lines = ["CIO OPERATOR PRODUCT", ""]
    for e in product.get("entries") or []:
        sym = e.get("symbol") or ""
        lines.append(f"CIO DECISION — {sym} {e.get('cio_decision')}".strip())
        lines.append(f"What changed: {e.get('what_changed')}")
        if e.get("why_it_matters"):
            lines.append(f"Why it matters: {e.get('why_it_matters')}")
        lines.append(f"Your action: {e.get('what_should_i_do')}")
        if e.get("why"):
            lines.append(f"Why: {e.get('why')}")
        if e.get("confidence") is not None:
            lines.append(f"Confidence: {e.get('confidence')}")
        if e.get("counter_evidence"):
            lines.append(f"Counterpoint: {e.get('counter_evidence')}")
        lines.append("")
    return "\n".join(lines).strip()
