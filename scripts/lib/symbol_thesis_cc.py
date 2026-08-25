"""Command Center projections for UNIVERSE & THESES (read-only).

Extends existing CIO/Advisory surfaces — does not create a second dashboard.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.symbol_thesis_attach import (
    thesis_fields_for_symbol,
    universe_metrics,
    watchlist_materiality,
)
from scripts.lib.symbol_thesis_coverage import build_coverage_report, symbol_thesis_id
from scripts.lib.symbol_thesis_queue import load_symbol_research_queue
from scripts.lib.symbol_thesis_research import propose_prioritized_research, research_requests_for_symbol
from scripts.lib.symbol_thesis_review import daily_thesis_changes
from scripts.lib.research_prompt_context import latest_delta
from scripts.lib.symbol_universe import reconcile_universe


def _transferson_denominators(root: Path) -> dict[str, Any]:
    try:
        from scripts.lib.transferson_universe import load_universe, operator_denominators
        return operator_denominators(load_universe(root=root))
    except Exception as exc:
        return {
            "schema": "TransfersonOperatorDenominators@v1",
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "not_the_canonical_universe": True,
            "authority": AUTHORITY,
        }

AUTHORITY = "READ_ONLY_ADVISORY"

# Category / aggregate labels that leaked into the symbol column. Not tickers —
# exclude from material cards or bucket OTHER (CUSIP bucketing stays separate).
NON_TICKER_SYMBOLS = frozenset({
    "HEALTH",
    "DAY_SWING",
    "POSITION",
    "LONG_TERM_COMPOUNDER",
    "CATEGORY",
    "SECTOR",
    "STYLE",
    "AGGREGATE",
    "UNKNOWN_CATEGORY",
})


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def membership_exit_reason(prev_memberships: list[str], curr_memberships: list[str], *, held: bool) -> Optional[str]:
    """Explain why a symbol left reentry/watchlist/opportunity — never silent drop."""
    prev, curr = set(prev_memberships or []), set(curr_memberships or [])
    left = prev - curr
    if not left:
        return None
    if held or "HELD" in curr:
        return "CURRENTLY_HELD"
    if "RETIRED" in curr:
        return "RETIRED"
    if not curr:
        return "SOURCE_REMOVED"
    if "OPPORTUNITY" in left or "REENTRY" in left or "WATCHLIST" in left:
        return "NO_LONGER_MATERIAL"
    return "OTHER"


def _is_cusip(symbol: str) -> bool:
    """True for unresolved CUSIP/SEDOL-style identifiers (e.g. 12507E201).

    Real tickers are 1–5 alpha/dot/dash chars. A leading-digit alphanumeric
    code of length 6–9 is a bond/identifier, not a tradable equity symbol.
    """
    s = str(symbol or "").strip()
    return bool(re.fullmatch(r"[0-9][0-9A-Za-z]{5,8}", s))


def _is_non_ticker(symbol: str) -> bool:
    """True for category/aggregate labels that must not render as material tickers."""
    s = str(symbol or "").strip().upper()
    return bool(s) and s in NON_TICKER_SYMBOLS


def _membership_bucket(r: dict[str, Any]) -> str:
    """Canonical single membership label for a universe row (HELD/REENTRY/WATCH/…).

    CUSIP/unresolved identifiers are pulled out of the HELD sort entirely so
    they no longer crowd the top of the 80-name operator list. Non-ticker
    category labels are OTHER (never HELD/REENTRY/WATCH material tickers).
    """
    sym = str(r.get("symbol") or "")
    if _is_cusip(sym):
        return "BONDS_UNRESOLVED"
    if _is_non_ticker(sym):
        return "OTHER"
    m = set(r.get("memberships") or [])
    if "HELD" in m:
        return "HELD"
    if "REENTRY" in m or "FORMER_HOLDING" in m:
        return "REENTRY"
    if "OPPORTUNITY" in m or "WATCHLIST" in m:
        return "WATCH"
    return "OTHER"


_BUCKET_PRIORITY = {
    "HELD": 0,
    "REENTRY": 1,
    "WATCH": 2,
    "OTHER": 3,
    "BONDS_UNRESOLVED": 4,
}


def build_universe_theses_projection(
    *,
    root: Path | str | None = None,
    include_proposed_research: bool = True,
    symbol_limit: int = 80,
) -> dict[str, Any]:
    """Top-level UNIVERSE & THESES Command Center projection."""
    root = _root(root)
    metrics = universe_metrics(root=root)
    report = build_coverage_report(root=root, material_only=False)
    daily = daily_thesis_changes(root=root)
    try:
        from scripts.lib.universe_projection import build_universe_projection
        canonical_universe = build_universe_projection(root=root)
    except Exception as exc:
        canonical_universe = {
            "schema": "UniverseProjection@v1",
            "ok": False,
            "error": f"{type(exc).__name__}:{exc}",
            "authority": AUTHORITY,
            "financial_action": False,
        }

    material_rows = [r for r in (report.get("rows") or []) if r.get("material")]
    non_ticker_excluded = sum(
        1 for r in material_rows if _is_non_ticker(str(r.get("symbol") or ""))
    )
    # Prefer HELD / REENTRY / WATCH for the operator card list; park CUSIPs and
    # unresolved identifiers in a trailing "Bonds & unresolved" bucket so they
    # no longer crowd the top of the 80. Non-ticker category labels are excluded
    # from the material ticker card list (not shown as investable names).
    material_for_cards = [
        r for r in material_rows if not _is_non_ticker(str(r.get("symbol") or ""))
    ]

    def _sort_key(r: dict[str, Any]) -> tuple:
        bucket_pri = _BUCKET_PRIORITY.get(_membership_bucket(r), 4)
        state_pri = 0 if r.get("coverage_state") in {"CONFLICTED", "STALE", "RESEARCH_REQUIRED"} else 1
        return (bucket_pri, state_pri, r.get("symbol") or "")

    material_for_cards.sort(key=_sort_key)
    cards = []
    for r in material_for_cards[:symbol_limit]:
        cards.append({
            "symbol": r["symbol"],
            "memberships": r.get("memberships"),
            "bucket": _membership_bucket(r),
            "portfolio_role": (r.get("portfolio_role") or {}).get("portfolio_role"),
            "portfolio_role_source": (r.get("portfolio_role") or {}).get("source"),
            "thesis_state": r.get("coverage_state"),
            "mint_state": r.get("coverage_state"),
            "stance": r.get("thesis_stance"),
            "confidence": None,
            "last_reviewed": None,
            "next_review": None,
            "thesis_version": r.get("thesis_pin"),
            "research_gaps": r.get("research_gaps") or [],
            "reentry_state": r.get("reentry_state"),
            "opportunity_rank": r.get("opportunity_rank"),
            "materiality": watchlist_materiality(
                r.get("memberships") or [],
                thesis_state=str(r.get("coverage_state") or ""),
                opp_rank=r.get("opportunity_rank"),
            ),
        })

    proposed = None
    if include_proposed_research:
        proposed = propose_prioritized_research(root=root, limit=25)

    bonds_unresolved = sum(
        1 for r in material_for_cards if _membership_bucket(r) == "BONDS_UNRESOLVED"
    )

    return {
        "schema": "UniverseThesesProjection@v1",
        "section": "UNIVERSE_AND_THESES",
        "as_of": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "not_the_canonical_universe": True,
        "canonical_contract": "TransfersonUniverseManifest@v1",
        "transferson_denominators": _transferson_denominators(root),
        "metrics": {
            "material_universe": metrics.get("material"),
            "universe_union": metrics.get("universe_union"),
            "thesis_covered_label": "thesis-covered = current+thin / eligible material subset; not Transferson universe",
            "current_thesis": metrics.get("current"),
            "research_required": metrics.get("research_required"),
            "stale": metrics.get("stale"),
            "conflicted": metrics.get("conflicted"),
            "insufficient_data": metrics.get("insufficient_data"),
            "bonds_unresolved": bonds_unresolved,
            "non_ticker_excluded": non_ticker_excluded,
            "unknown_role": metrics.get("role_unknown"),
            "coverage_pct": metrics.get("coverage_pct_material"),
            "substantive_pct": metrics.get("substantive_pct_material"),
            "thin": metrics.get("thin"),
            "held": metrics.get("held"),
            "held_current": metrics.get("held_current"),
            "held_thin": metrics.get("held_thin"),
            "held_coverage_pct": metrics.get("held_coverage_pct"),
            "held_substantive_pct": metrics.get("held_substantive_pct"),
            "percentage_definitions": metrics.get("percentage_definitions") or {},
            "open_thesis_research_proposed": (proposed or {}).get("counts", {}).get("proposed") if proposed else 0,
            "desk": metrics.get("desk"),
        },
        "daily_thesis_changes": daily,
        "universe_projection": canonical_universe,
        "symbols": cards,
        "proposed_research": proposed,
        "note": (
            "Read-only projection. Proposed research is DRY — not enqueued. "
            "No production thesis backfill."
        ),
    }


def build_symbol_thesis_card(
    symbol: str,
    *,
    root: Path | str | None = None,
    research_rows: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Per-symbol drill-down for Command Center / Ask CIO context."""
    root = _root(root)
    sym = str(symbol or "").upper()
    fields = thesis_fields_for_symbol(sym, root=root)
    store = CIOThesisStore(
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )
    tid = fields.get("symbol_thesis_id") or symbol_thesis_id(sym)
    history = store.list_versions(tid, limit=20)
    hist_rows = []
    for h in history:
        hist_rows.append({
            "thesis_version": h.get("thesis_version"),
            "published_at": h.get("published_ts"),
            "reason_for_change": h.get("change_note"),
            "stance": h.get("stance"),
            "summary": (h.get("summary") or ""),
            "evidence_refs": h.get("evidence_refs") or [],
        })
    research = research_requests_for_symbol(sym, root=root)
    uni = reconcile_universe(root)
    urec = (uni.get("symbols") or {}).get(sym) or {}
    queue = (
        load_symbol_research_queue(sym, rows=research_rows)
        if research_rows is not None
        else load_symbol_research_queue(sym)
    )
    cio_action = _cio_action_for_symbol(sym, root=root)
    research_delta = latest_delta(sym, root=root)
    ntf = None
    try:
        from scripts.lib.cio_command_center import _trust_notification
        ntf = _trust_notification()
    except Exception:
        ntf = None

    return {
        "schema": "SymbolThesisCard@v1",
        "as_of": _now(),
        "authority": AUTHORITY,
        "financial_action": False,
        "symbol": sym,
        "memberships": fields.get("memberships") or urec.get("memberships") or [],
        "portfolio_role": fields.get("portfolio_role"),
        "portfolio_role_source": fields.get("portfolio_role_source"),
        "portfolio_role_provenance": fields.get("portfolio_role_provenance"),
        "thesis_state": fields.get("thesis_state"),
        "thesis_stance": fields.get("thesis_stance"),
        "thesis_confidence": fields.get("thesis_confidence"),
        "last_reviewed": fields.get("last_reviewed"),
        "next_review_at": fields.get("next_review_at"),
        "symbol_thesis_id": tid,
        "symbol_thesis_version": fields.get("symbol_thesis_version"),
        "why_in_universe": {
            "memberships": fields.get("memberships") or urec.get("memberships") or [],
            "held": urec.get("held"),
            "reentry": urec.get("reentry"),
            "opportunity": urec.get("opportunity"),
            "former": urec.get("former"),
        },
        "core_thesis": fields.get("thesis_summary") or "No living thesis",
        "positive_evidence": fields.get("evidence_for") or [],
        "counter_thesis": fields.get("counter_evidence") or [],
        "evidence_provenance": {
            "research_id": (research_delta or {}).get("research_id"),
            "delta_id": (research_delta or {}).get("delta_id"),
            "classification": (research_delta or {}).get("classification"),
            "provider": (research_delta or {}).get("provider"),
            "model": (research_delta or {}).get("model"),
            "evidence_as_of": (research_delta or {}).get("evidence_as_of"),
            "source_refs": (research_delta or {}).get("source_refs") or [],
            "source_quality": (research_delta or {}).get("source_quality"),
            "freshness": (research_delta or {}).get("freshness"),
            "authority": AUTHORITY,
        },
        "invalidation": fields.get("invalidation_conditions") or [],
        "market_sector_fit": fields.get("thesis_summary"),
        "why_owned_or_watched": fields.get("why_owned_or_watched"),
        "why_exited": fields.get("why_exited"),
        "what_changed_since_exit": fields.get("what_changed_since_exit"),
        "what_would_change": fields.get("what_would_change") or [],
        "reentry_state": (urec.get("reentry") or {}).get("intel_state"),
        "opportunity_rank": (urec.get("opportunity") or {}).get("rank") if urec.get("opportunity") else None,
        "research_gaps": fields.get("research_gaps") or [],
        "proposed_research": research,
        "active_research": queue.get("active_research") or [],
        "recent_completed_research": queue.get("recent_completed_research") or [],
        "research_queue_source": queue.get("source"),
        "research_queue_open_count": int(queue.get("open_count") or 0),
        "research_queue_oldest_wait_seconds": queue.get("oldest_wait_seconds"),
        "research_queue_oldest_wait_human": queue.get("oldest_wait_human"),
        "financial_senses_refs": [],
        "lesson_refs": [],
        "memory_refs": [],
        "thesis_history": hist_rows,
        "what_changed": hist_rows[0].get("reason_for_change") if hist_rows else None,
        "cio_action": cio_action,
        "advisory_verdict": (cio_action or {}).get("action") if cio_action else None,
        "notification": ntf,
        "suppression_reason": (ntf or {}).get("suppression_reason") if ntf else None,
        "note": "No hidden chain-of-thought. Supporting evidence IDs are drillable when present. Empty research lists mean the queue was unavailable or idle — not invented jobs.",
    }


def _cio_action_for_symbol(symbol: str, root: Path) -> Optional[dict[str, Any]]:
    """Fail-soft CIO action book row for this symbol. Never invents RE_ENTER."""
    try:
        from scripts.lib.cio_investment_product import load_brief
        brief = load_brief(root) or {}
    except Exception:
        return None
    act = brief.get("action_book") or {}
    buckets = (
        "DO_NOW", "WATCH_CLOSELY", "RE_ENTER_IF", "NEW_POSITION_IF",
        "HOLD_CASH_FOR", "AVOID", "RESEARCH_NEXT",
    )
    for bucket in buckets:
        rows = act.get(bucket) if isinstance(act.get(bucket), list) else []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("symbol") or "").upper() == symbol:
                return {
                    "bucket": bucket,
                    "action": r.get("action"),
                    "why": r.get("why"),
                    "decision_id": r.get("decision_id"),
                    "previous_action": r.get("previous_action"),
                    "reason_codes": r.get("reason_codes") or [],
                    "research_delta": r.get("research_delta"),
                    "thesis_version": r.get("thesis_version"),
                    "source_freshness": r.get("source_freshness"),
                    "authority": AUTHORITY,
                    "financial_action": False,
                }
    return None


def ask_cio_symbol_context(symbol: str, *, root: Path | str | None = None) -> dict[str, Any]:
    """Operator-request context for questions like 'Why aren't we back in SCHG?'."""
    card = build_symbol_thesis_card(symbol, root=root)
    gaps = card.get("proposed_research") or []
    return {
        "schema": "AskCioSymbolThesisContext@v1",
        "authority": AUTHORITY,
        "financial_action": False,
        "trading_execution_authority": False,
        "symbol": card["symbol"],
        "current_symbol_thesis": {
            "state": card.get("thesis_state"),
            "version": card.get("symbol_thesis_version"),
            "stance": card.get("thesis_stance"),
            "summary": card.get("core_thesis"),
        },
        "portfolio_role": card.get("portfolio_role"),
        "portfolio_role_provenance": card.get("portfolio_role_source"),
        "prior_holding_exit_context": {
            "why_owned": card.get("why_owned_or_watched"),
            "why_exited": card.get("why_exited"),
            "what_changed_since_exit": card.get("what_changed_since_exit"),
        },
        "reentry_state": card.get("reentry_state"),
        "opportunity_rank": card.get("opportunity_rank"),
        "counter_thesis": card.get("counter_thesis"),
        "what_changes_call": card.get("what_would_change"),
        "research_gaps": card.get("research_gaps"),
        "proposed_specific_research": gaps[:3],
        "transparent_if_missing": (
            card.get("thesis_state") in {
                "RESEARCH_REQUIRED", "INSUFFICIENT_DATA", "STALE", "CONFLICTED"
            }
        ),
        "as_of": _now(),
    }
