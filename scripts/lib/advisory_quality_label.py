"""Operator-facing Advisory Desk quality labels (READ_ONLY_ADVISORY).

Separates mark/identity/allocation/mechanical-desk state from "evidence pack
incomplete" so the Quality column does not dump everything into DATA_UNAVAILABLE.
"""
from __future__ import annotations

from typing import Any


# Evidence gaps that agents can actually chase via data_gap_resolver / research jobs.
REQUEUEABLE_GAPS = frozenset({
    "catalysts",
    "earnings_calendar",
    "technicals",
    "hermes_health",
    "agent_opinions",
    "external_research",
    "analyst_context",
    "price_action",
})

# Map desk evidence_gap → data_gap_registry.gap_type
GAP_TYPE_MAP = {
    "catalysts": "missing_catalyst",
    "earnings_calendar": "missing_market_data",
    "technicals": "missing_market_data",
    "price_action": "missing_market_data",
    "analyst_context": "missing_market_data",
    "hermes_health": "explicit",
    "agent_opinions": "explicit",
    "external_research": "explicit",
}


def classify_advisory_quality(row: dict[str, Any], dq: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {kind, label, detail, requeueable, requeue_gaps} for one desk row."""
    dq = dq if isinstance(dq, dict) else (row.get("data_quality") or {})
    row_class = str(row.get("row_class") or "")
    verdict = str(row.get("verdict") or "")
    symbol = str(row.get("symbol") or "")
    gaps = [str(g) for g in (dq.get("evidence_gaps") or row.get("evidence_bundle", {}).get("evidence_gaps") or [])]
    gap_count = int(dq.get("gap_count") if dq.get("gap_count") is not None else len(gaps))
    ev = int(dq.get("evidence_count") or 0)
    raw_q = str(dq.get("quality") or "").upper()
    suppressed = bool(dq.get("action_suppressed") or row.get("verdict_suppressed"))
    setup = str(row.get("setup_state") or "").upper()
    reentry_state = str(row.get("reentry_state") or "").upper()
    rationale = str(row.get("rationale") or "")

    # 1) Mark conflict — highest clarity
    if suppressed or "DATA CONFLICT" in (dq.get("banner") or ""):
        return {
            "kind": "MARK_CONFLICT",
            "label": "MARK CONFLICT",
            "detail": "Conflicting mark/MV/target — action suppressed until reconcile",
            "requeueable": False,
            "requeue_gaps": [],
            "raw_quality": raw_q or None,
        }

    # 2) Allocation semantics
    if row_class == "allocation":
        if symbol.startswith("ALLOC:cash:") or "Per-account drift not evaluated" in rationale:
            return {
                "kind": "ALLOC_NOT_SCORED",
                "label": "NOT SCORED VS MODEL",
                "detail": "Per-account cash is informational; use aggregate ALLOC:cash",
                "requeueable": False,
                "requeue_gaps": [],
                "raw_quality": raw_q or None,
            }
        if verdict == "INSUFFICIENT_DATA" or "CUSIP" in rationale or "unresolved" in rationale.lower():
            return {
                "kind": "ALLOC_UNMEASURED",
                "label": "UNRESOLVED CUSIPS",
                "detail": "Fixed-income weight unknown until CUSIP→instrument mapping",
                "requeueable": False,
                "requeue_gaps": [],
                "raw_quality": raw_q or None,
            }

    # 3) Unresolved identity (holding CUSIP)
    if verdict == "INSUFFICIENT_DATA" and (
        "Unresolvable symbol" in rationale or "CUSIP" in rationale or "identifier" in rationale.lower()
    ):
        return {
            "kind": "UNRESOLVED_IDENTITY",
            "label": "UNRESOLVED ID",
            "detail": "Symbol/CUSIP cannot be resolved to an equity — not a delisting",
            "requeueable": False,
            "requeue_gaps": [],
            "raw_quality": raw_q or None,
        }

    # 4) Watch technical pipeline
    if row_class == "watchlist" and (
        "STALE" in setup or "BLOCKED" in setup or "technical snapshot is STALE" in rationale
        or "DETERMINISTIC_FAIL" in rationale
    ):
        return {
            "kind": "TECH_PIPELINE_STALE",
            "label": "TECH CACHE STALE",
            "detail": "Watch technical/indicator pipeline stale — not a thesis gap; refresh indicator_cache",
            "requeueable": True,
            "requeue_gaps": ["technicals"] if "technicals" in gaps or True else [],
            "raw_quality": raw_q or None,
        }

    # 5) Re-entry mechanical vs diligence
    if row_class == "closed_journal" or verdict == "RE_ENTER":
        if "MISSING MARKET" in reentry_state:
            return {
                "kind": "REENTRY_MISSING_MARKET",
                "label": "NEED PRICE/RSI",
                "detail": "Re-entry desk needs live price + RSI from data broker",
                "requeueable": True,
                "requeue_gaps": ["price_action"],
                "raw_quality": raw_q or None,
            }
        if "MISSING PLAN" in reentry_state:
            return {
                "kind": "REENTRY_MISSING_PLAN",
                "label": "NEED ENTRY PLAN",
                "detail": "Market exists but no validated entry range yet",
                "requeueable": True,
                "requeue_gaps": [g for g in gaps if g in REQUEUEABLE_GAPS] or ["external_research"],
                "raw_quality": raw_q or None,
            }
        if any(x in reentry_state for x in ("READY", "NEAR", "OVERSOLD", "OVERBOUGHT", "WASH")):
            rq = [g for g in gaps if g in REQUEUEABLE_GAPS]
            return {
                "kind": "REENTRY_MECHANICAL_OK",
                "label": "DESK OK · EVIDENCE THIN" if gap_count else "DESK OK",
                "detail": (
                    f"Re-entry state is mechanical ({reentry_state or 'set'}). "
                    f"Evidence pack {ev} items, {gap_count} gaps — not 'no data'."
                ),
                "requeueable": bool(rq),
                "requeue_gaps": rq,
                "raw_quality": raw_q or None,
            }

    # 6) Hub leads with empty packs
    if row_class == "watchlist_hub" and ev == 0:
        return {
            "kind": "HUB_UNRESEARCHED",
            "label": "HUB LEAD · NO PACK",
            "detail": "Watch Hub opportunity — not on personal watch; no diligence pack yet",
            "requeueable": False,
            "requeue_gaps": [],
            "raw_quality": raw_q or None,
        }

    # 7) Holdings / watch with thin evidence but not "unavailable"
    if gap_count > 0:
        rq = [g for g in gaps if g in REQUEUEABLE_GAPS]
        if raw_q == "STALE" or "review thesis freshness" in rationale.lower():
            return {
                "kind": "THESIS_STALE",
                "label": "THESIS STALE",
                "detail": f"Held long / thesis freshness review; {gap_count} evidence gaps",
                "requeueable": bool(rq),
                "requeue_gaps": rq,
                "raw_quality": raw_q or None,
            }
        return {
            "kind": "EVIDENCE_THIN",
            "label": "EVIDENCE THIN",
            "detail": f"{ev} evidence items · missing: {', '.join(gaps[:6]) or '—'}",
            "requeueable": bool(rq),
            "requeue_gaps": rq,
            "raw_quality": raw_q or None,
        }

    # 8) Fallthrough — prefer CURRENT/OK over raw DATA_UNAVAILABLE when pack is ok
    if raw_q in ("", "DATA_UNAVAILABLE") and ev > 0 and gap_count == 0:
        return {
            "kind": "OK",
            "label": "PACK OK",
            "detail": f"{ev} symbol-specific evidence items",
            "requeueable": False,
            "requeue_gaps": [],
            "raw_quality": raw_q or None,
        }
    if raw_q:
        return {
            "kind": f"MARK_{raw_q}",
            "label": raw_q.replace("_", " "),
            "detail": f"Mark/provenance quality={raw_q}; ev {ev}",
            "requeueable": False,
            "requeue_gaps": [],
            "raw_quality": raw_q,
        }
    return {
        "kind": "OK",
        "label": "OK",
        "detail": f"ev {ev}",
        "requeueable": False,
        "requeue_gaps": [],
        "raw_quality": None,
    }
