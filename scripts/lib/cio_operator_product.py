"""CIOOperatorProduct@v1 — one operator-facing product, many renderers."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.lib.atomic_json_store import append_jsonl, atomic_write_json
from scripts.lib.canonical_store_registry import load_json_store, resolve_store
from scripts.lib.product_availability import AVAILABLE, UNAVAILABLE_REASONS, availability_payload, canonicalize_reason

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "CIOOperatorProduct@v1"
ACTIONS = ("HOLD", "WATCH", "REVIEW", "TRIM", "REENTER", "AVOID", "NO_ACTION", "HOLD_CASH", "WAIT")
WHEN = ("NOW", "TODAY", "NEXT_SESSION", "WATCH_ONLY", "NOTHING", "NONE")
REQUIRED_SECTIONS = (
    "product_id",
    "generation_id",
    "as_of",
    "executive_summary",
    "action_now",
    "decisions",
    "standing_decisions",
    "portfolio",
    "cash",
    "risk",
    "watch",
    "reentry",
    "sector",
    "industry",
    "themes",
    "catalysts",
    "earnings",
    "macro",
    "research_changes",
    "research_gaps",
    "specialist_disagreements",
    "outcomes_learning",
    "data_quality",
    "policy_gaps",
    "next_reviews",
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _map_action(raw: str) -> str:
    a = str(raw or "").upper().replace(" ", "_")
    aliases = {
        "RE_ENTER": "REENTER", "HOLD_POSTURE": "HOLD", "WAIT": "WAIT",
        "DO_NOW": "REVIEW", "WATCH_CLOSELY": "WATCH",
    }
    a = aliases.get(a, a)
    return a if a in ACTIONS else "REVIEW"


def _entry_from_rec(row: dict[str, Any]) -> dict[str, Any]:
    action = _map_action(row.get("recommended_action") or row.get("action") or row.get("title"))
    when = "NOW" if str(row.get("priority") or "").upper() == "HIGH" else "NEXT_SESSION"
    if action in {"HOLD", "HOLD_CASH", "NO_ACTION"}:
        when = "NOTHING"
    if action in {"WATCH", "WAIT"}:
        when = "WATCH_ONLY"
    return {
        "what_changed": row.get("title") or row.get("action") or "CIO observation",
        "why_it_matters": row.get("description") or row.get("rationale") or "",
        "cio_decision": action,
        "what_should_i_do": when,
        "operator_action": when,
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


def _last_valid_ref(root: Path | str | None) -> dict[str, Any] | None:
    loc = load_json_store("cio.operator_product.current", root=root)
    if loc.get("available") and isinstance(loc.get("data"), dict):
        d = loc["data"]
        if d.get("available") and d.get("schema") == SCHEMA:
            return {
                "product_id": d.get("product_id"),
                "generation_id": d.get("generation_id"),
                "as_of": d.get("as_of"),
                "path": loc.get("path"),
            }
    return None


def unavailable(*, reason: str, detail: str | None = None, path: str | None = None,
                last_valid_product: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = availability_payload(
        reason=reason,
        detail=detail,
        path=path,
        last_valid_product=last_valid_product,
    )
    payload.update({
        "schema": SCHEMA,
        "entries": [],
        "decisions": [],
        "action_now": [],
        "canonical": True,
        "gui_is_projection": True,
    })
    # Preserve explicit INVALID_SCHEMA contract.
    if payload["status"] == "INVALID_SCHEMA":
        payload["operator_data_quality"] = "DEGRADED"
    return payload


def _holdings_sections(root: Path | str | None) -> dict[str, Any]:
    hloc = load_json_store("portfolio.holdings.current", root=root)
    data_quality = {"state": "OK", "labels": []}
    portfolio: dict[str, Any] = {"holdings_n": 0, "source": "portfolio.holdings.current"}
    cash: dict[str, Any] = {"status": "UNKNOWN"}
    if not hloc.get("available"):
        data_quality = {
            "state": "MISSING_REQUIRED_INPUT" if hloc.get("reason") == "PRODUCER_NOT_RUN" else hloc.get("status") or "UNAVAILABLE",
            "labels": ["HOLDINGS_UNAVAILABLE"],
            "note": "LAST_KNOWN_GOOD not present — consumers must not treat this as an empty book.",
        }
        return {"portfolio": portfolio, "cash": cash, "data_quality": data_quality}
    doc = hloc["data"] if isinstance(hloc.get("data"), dict) else {}
    holds = [h for h in (doc.get("holdings") or []) if isinstance(h, dict)]
    if doc.get("write_rejected") or doc.get("sanity_floor_blocked"):
        data_quality = {
            "state": "LAST_KNOWN_GOOD",
            "labels": ["WRITE_REJECTED", "LAST_KNOWN_GOOD"],
            "note": "Incoming holdings write rejected; prior snapshot preserved.",
        }
    cash_rows = [h for h in holds if h.get("is_cash")]
    equity = [h for h in holds if not h.get("is_cash")]
    cash_usd = sum(float(h.get("market_value") or 0) for h in cash_rows)
    equity_usd = sum(float(h.get("market_value") or 0) for h in equity)
    portfolio = {
        "holdings_n": len(equity),
        "equity_usd": round(equity_usd, 2),
        "source": "portfolio.holdings.current",
        "as_of": doc.get("as_of") or doc.get("generated_at"),
        "freshness_note": doc.get("_freshness_note"),
    }
    cash = {
        "cash_usd": round(cash_usd, 2),
        "cash_n": len(cash_rows),
        "status": "PRESENT" if cash_rows else "UNCONFIRMED",
    }
    return {"portfolio": portfolio, "cash": cash, "data_quality": data_quality}


def _ops_degradation(root: Path | str | None) -> dict[str, Any] | None:
    """Ops health enters the product only when it changes investment reliability."""
    from scripts.lib.ops_health_routing import cio_capability_impact
    loc = resolve_store("ops.health", root=root)
    path = Path(loc.get("path") or loc.get("primary_path") or "")
    if not path.exists():
        return None
    return cio_capability_impact(path)


def _generation_id(brief: dict[str, Any], entries: list[dict[str, Any]]) -> str:
    payload = {
        "product_id": brief.get("product_id") or brief.get("decision_id"),
        "final_position": brief.get("final_position"),
        "summary": brief.get("summary") if isinstance(brief.get("summary"), str) else (
            (brief.get("summary") or {}) if isinstance(brief.get("summary"), dict) else None
        ),
        "actions": [(e.get("symbol"), e.get("cio_decision"), e.get("what_should_i_do")) for e in entries],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def build_operator_product(*, root: Path | str | None = None, persist: bool = False,
                           supplemental: dict[str, Any] | None = None) -> dict[str, Any]:
    loc = load_json_store("cio.product.current", root=root)
    last_valid = _last_valid_ref(root)
    if loc.get("reason") == "INVALID_SCHEMA" or loc.get("status") == "INVALID_SCHEMA":
        return unavailable(
            reason="INVALID_SCHEMA",
            detail=str(loc.get("error") or loc.get("reason")),
            path=loc.get("path"),
            last_valid_product=last_valid,
        )
    if not loc.get("available"):
        reason = canonicalize_reason(loc.get("reason") or "PRODUCER_NOT_RUN")
        return unavailable(reason=reason, detail=str(loc.get("reason")), path=loc.get("path"),
                           last_valid_product=last_valid)
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
            entries.append(_entry_from_rec({
                "title": "CIO posture",
                "description": str(summary),
                "recommended_action": brief.get("final_position") or "HOLD",
            }))

    holdings = _holdings_sections(root)
    action_now = [e for e in entries if e.get("what_should_i_do") == "NOW"]
    standing = [e for e in entries if e.get("cio_decision") in {"HOLD", "HOLD_CASH", "WATCH", "WAIT", "NO_ACTION"}]
    exec_summary = brief.get("summary")
    if isinstance(exec_summary, dict):
        exec_summary = exec_summary.get("headline") or exec_summary.get("narrative") or json.dumps(exec_summary)[:280]
    if not exec_summary:
        exec_summary = brief.get("temperament") or "CIO standing posture."

    reentry = brief.get("reentry_book") if isinstance(brief.get("reentry_book"), dict) else {}
    opportunity = brief.get("opportunity_book") if isinstance(brief.get("opportunity_book"), dict) else {}
    thesis_changes = brief.get("thesis_changes_today") or []

    data_quality = dict(holdings["data_quality"])
    ops = _ops_degradation(root)
    policy_gaps: list[Any] = []
    if ops and ops.get("affects_investment_reliability"):
        data_quality.setdefault("labels", []).append("CIO_DATA_GAP")
        data_quality["ops_impact"] = ops.get("prose")
        policy_gaps.append(ops.get("prose"))

    if supplemental:
        # Fold Trade AI Brief / morning ops facts — not competing CIO truth.
        extra_ops = {k: supplemental[k] for k in supplemental if k in {
            "health", "stops", "dividends", "paper", "overnight", "closed_trades",
        }}
        if extra_ops:
            data_quality["supplemental_ops"] = extra_ops

    gen = _generation_id(brief, entries)
    product = {
        "schema": SCHEMA,
        "available": True,
        "status": AVAILABLE,
        "reason": None,
        "product_id": brief.get("product_id") or brief.get("decision_id") or f"op_{gen}",
        "generation_id": gen,
        "as_of": brief.get("as_of") or _now(),
        "source_store": "cio.product.current",
        "source_path": loc.get("path"),
        "executive_summary": str(exec_summary),
        "action_now": action_now,
        "decisions": entries,
        "standing_decisions": standing,
        "portfolio": holdings["portfolio"],
        "cash": holdings["cash"],
        "risk": brief.get("risk") or {"note": "risk surface is the standing decision list plus holdings last-known-good"},
        "watch": opportunity.get("watch") or brief.get("watch") or [],
        "reentry": {
            "count": reentry.get("count"),
            "counts": reentry.get("counts"),
            "note": reentry.get("note"),
        },
        "sector": [],
        "industry": [],
        "themes": list(brief.get("themes") or []),
        "catalysts": list(brief.get("catalysts") or []),
        "earnings": list(brief.get("earnings") or []),
        "macro": brief.get("macro") or brief.get("temperament"),
        "research_changes": thesis_changes if isinstance(thesis_changes, list) else [],
        "research_gaps": list(brief.get("research_gaps") or []),
        "specialist_disagreements": list(brief.get("specialist_disagreements") or []),
        "outcomes_learning": {"source": "cio.outcomes", "influence_from_bug_duplicates": 0},
        "data_quality": data_quality,
        "policy_gaps": policy_gaps,
        "next_reviews": [e.get("next_review") for e in entries if e.get("next_review")],
        "entries": entries[:20],
        "competing_products": [],
        "competing_products_removed": True,
        "canonical": True,
        "material": bool(action_now) or any(
            e.get("cio_decision") in {"TRIM", "REENTER", "AVOID", "REVIEW"} for e in entries
        ),
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "gui_is_projection": True,
        "operator_data_quality": data_quality.get("state") or "OK",
    }
    if persist:
        out = resolve_store("cio.operator_product.current", root=root)
        path = Path(out["primary_path"])
        atomic_write_json(path, product)
        hist = resolve_store("cio.operator_product.history", root=root)
        append_jsonl(Path(hist["primary_path"]), {
            "as_of": product.get("as_of"),
            "product_id": product.get("product_id"),
            "generation_id": product.get("generation_id"),
            "material": product.get("material"),
        })
        product["persisted_path"] = str(path)
    return product


def render_human(product: dict[str, Any]) -> str:
    from scripts.lib.operator_human_renderer import render_product
    return render_product(product)
