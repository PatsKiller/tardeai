"""Attach symbol-thesis coverage fields onto CIO book rows (fail-soft).

READ_ONLY_ADVISORY. Never invents why_owned/why_exited. Never grants RE_ENTER.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_theses import CIOThesisStore
from scripts.lib.portfolio_role import resolve_portfolio_role
from scripts.lib.symbol_thesis_coverage import (
    classify_symbol,
    research_gap_triggers,
    symbol_thesis_id,
)
from scripts.lib.symbol_universe import reconcile_universe

_CACHE: dict[str, Any] = {"root": None, "universe": None, "store": None, "by_sym": None}


def _root(root: Path | str | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parents[2]


def _load(root: Path) -> tuple[dict[str, Any], CIOThesisStore, dict[str, dict[str, Any]]]:
    key = str(root)
    if _CACHE.get("root") == key and _CACHE.get("by_sym") is not None:
        return _CACHE["universe"], _CACHE["store"], _CACHE["by_sym"]
    universe = reconcile_universe(root)
    store = CIOThesisStore(
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )
    by_sym: dict[str, dict[str, Any]] = {}
    for sym, rec in (universe.get("symbols") or {}).items():
        by_sym[sym] = classify_symbol(sym, universe_rec=rec, store=store, root=root)
    _CACHE.update({"root": key, "universe": universe, "store": store, "by_sym": by_sym})
    return universe, store, by_sym


def clear_cache() -> None:
    _CACHE.update({"root": None, "universe": None, "store": None, "by_sym": None})


def thesis_fields_for_symbol(symbol: str, *, root: Path | str | None = None) -> dict[str, Any]:
    """Return book-attachable thesis projection for one symbol."""
    root = _root(root)
    try:
        universe, store, by_sym = _load(root)
    except Exception as exc:
        return {
            "symbol": str(symbol).upper(),
            "symbol_thesis_id": None,
            "symbol_thesis_version": None,
            "thesis_state": "INSUFFICIENT_DATA",
            "thesis_unavailable_reason": f"coverage_error:{exc}"[:160],
            "portfolio_role": "UNKNOWN",
            "portfolio_role_confidence": "LOW",
            "portfolio_role_source": "error",
            "research_gap_count": 0,
            "research_gaps": [],
            "authority": "READ_ONLY_ADVISORY",
        }
    sym = str(symbol or "").upper()
    cov = by_sym.get(sym)
    uni = (universe.get("symbols") or {}).get(sym) or {"memberships": [], "held": False}
    if cov is None:
        cov = classify_symbol(sym, universe_rec=uni, store=store, root=root)
    role = cov.get("portfolio_role") or resolve_portfolio_role(sym, universe_rec=uni, root=root)
    thesis = store.get_current(symbol_thesis_id(sym)) if cov.get("has_current_symbol_thesis") else None
    extra = {}
    if thesis:
        for k in (
            "why_owned_or_watched", "why_exited", "what_changed_since_exit",
            "evidence_for", "counter_evidence", "invalidation_conditions",
            "what_changes_my_mind", "research_gaps",
        ):
            if k in thesis:
                extra[k] = thesis.get(k)
            elif isinstance(thesis.get("extra"), dict) and k in thesis["extra"]:
                extra[k] = thesis["extra"][k]

    gaps = list(cov.get("research_gaps") or [])
    return {
        "symbol": sym,
        "symbol_thesis_id": cov.get("thesis_id"),
        "symbol_thesis_version": cov.get("thesis_pin") or cov.get("thesis_version"),
        "thesis_state": cov.get("coverage_state") or "INSUFFICIENT_DATA",
        "thesis_reason": cov.get("coverage_reason"),
        "thesis_stance": cov.get("thesis_stance") or (thesis or {}).get("stance"),
        "thesis_summary": cov.get("thesis_summary") or ((thesis or {}).get("summary") or None),
        "thesis_confidence": (thesis or {}).get("confidence"),
        "last_reviewed": (thesis or {}).get("published_ts") or (thesis or {}).get("updated_ts"),
        "next_review_at": (thesis or {}).get("next_review_at"),
        "portfolio_role": role.get("portfolio_role") or "UNKNOWN",
        "portfolio_role_confidence": role.get("confidence"),
        "portfolio_role_source": role.get("source"),
        "portfolio_role_provenance": role.get("evidence") or [],
        "memberships": cov.get("memberships") or uni.get("memberships") or [],
        "counter_thesis_state": (
            "PRESENT" if extra.get("counter_evidence") else
            ("REQUIRED" if cov.get("coverage_state") in (
                "RESEARCH_REQUIRED", "CONFLICTED", "STALE", "THIN"
            ) else "ABSENT")
        ),
        "what_would_change": extra.get("what_changes_my_mind") or [],
        "why_owned_or_watched": extra.get("why_owned_or_watched") or "DATA_UNAVAILABLE",
        "why_exited": extra.get("why_exited") or ("DATA_UNAVAILABLE" if "FORMER_HOLDING" in (cov.get("memberships") or []) or "REENTRY" in (cov.get("memberships") or []) else None),
        "what_changed_since_exit": extra.get("what_changed_since_exit") or None,
        "evidence_for": extra.get("evidence_for") or [],
        "counter_evidence": extra.get("counter_evidence") or [],
        "invalidation_conditions": extra.get("invalidation_conditions") or [],
        "research_gap_count": len(gaps),
        "research_gaps": gaps,
        "active_research_count": 0,  # filled by caller if queue available
        "desk_pin": cov.get("desk_pin"),
        "has_current_symbol_thesis": bool(cov.get("has_current_symbol_thesis")),
        "thesis_age_days": cov.get("thesis_age_days"),
        "sla_days": cov.get("sla_days"),
        "coverage_class": cov.get("coverage_class"),
        "fresh": bool(cov.get("fresh")),
        "age_gate_short_circuit": cov.get("age_gate_short_circuit"),
        "substantiveness_grade": cov.get("substantiveness_grade"),
        "substantiveness_bucket": cov.get("substantiveness_bucket"),
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
    }


def attach_thesis(row: dict[str, Any], *, root: Path | str | None = None) -> dict[str, Any]:
    """Copy row and merge thesis_* fields (non-destructive)."""
    out = dict(row)
    sym = str(row.get("symbol") or "").upper()
    if not sym:
        return out
    fields = thesis_fields_for_symbol(sym, root=root)
    out["thesis"] = fields
    # Flatten commonly consumed keys for book UIs
    for k in (
        "symbol_thesis_id", "symbol_thesis_version", "thesis_state", "thesis_stance",
        "portfolio_role", "portfolio_role_source", "portfolio_role_confidence",
        "research_gap_count", "research_gaps", "counter_thesis_state",
        "why_owned_or_watched", "why_exited", "what_changed_since_exit",
        "has_current_symbol_thesis",
    ):
        if k in fields:
            out[k] = fields[k]
    return out


def opportunity_actionability(row: dict[str, Any]) -> str:
    """Rank opportunity completeness: ACTIONABLE_NOW|NEAR_ACTIONABLE|RESEARCH_REQUIRED|WATCH|AVOID."""
    thesis_state = str(row.get("thesis_state") or (row.get("thesis") or {}).get("thesis_state") or "")
    status = str(row.get("status") or row.get("vs_former_holdings") or row.get("state") or "").upper()
    verdict = str(row.get("verdict") or row.get("governed_verdict") or "").upper()
    gaps = int(row.get("research_gap_count") or 0)
    if status == "AVOID" or verdict in {"EXIT", "TRIM"}:
        return "AVOID"
    if thesis_state in {"RESEARCH_REQUIRED", "STALE", "CONFLICTED", "INSUFFICIENT_DATA", "THIN"} or gaps > 0:
        if status in {"REENTER"} and verdict == "RE_ENTER" and thesis_state == "CURRENT" and gaps == 0:
            return "ACTIONABLE_NOW"
        if status in {"NEAR", "NEAR ENTRY", "IN_ZONE", "READY", "READY TO REVIEW"}:
            return "RESEARCH_REQUIRED"
        return "RESEARCH_REQUIRED"
    if status == "REENTER" or verdict == "RE_ENTER":
        return "ACTIONABLE_NOW"
    if status in {"NEAR", "NEAR ENTRY", "IN_ZONE", "READY", "READY TO REVIEW"}:
        return "NEAR_ACTIONABLE"
    return "WATCH"


def watchlist_materiality(memberships: list[str], *, thesis_state: str, opp_rank: Any = None) -> str:
    """Tier watchlist names — do NOT spawn research for all discovery rows.

    Returns one of:
      ACTIVE_MATERIAL | ACTIVE_LOW_PRIORITY | DISCOVERY_ONLY | RESEARCH_REQUIRED | RETIRED
    """
    m = set(memberships or [])
    if thesis_state == "RETIRED":
        return "RETIRED"
    if "HELD" in m:
        return "ACTIVE_MATERIAL"
    try:
        rank_i = int(opp_rank) if opp_rank is not None else None
    except (TypeError, ValueError):
        rank_i = None
    if "OPPORTUNITY" in m or (rank_i is not None and rank_i <= 20):
        return "ACTIVE_MATERIAL"
    if "REENTRY" in m or "FORMER_HOLDING" in m:
        return "ACTIVE_MATERIAL"
    if thesis_state in {"RESEARCH_REQUIRED", "STALE", "CONFLICTED", "THIN"} and (
        "WATCHLIST" in m or "OPPORTUNITY" in m or "REENTRY" in m
    ):
        # Material membership already returned above; watchlist-only research → flag
        if "WATCHLIST" in m and not (m & {"HELD", "REENTRY", "FORMER_HOLDING", "OPPORTUNITY"}):
            return "RESEARCH_REQUIRED"
        return "ACTIVE_LOW_PRIORITY"
    if "WATCHLIST" in m:
        return "DISCOVERY_ONLY"
    return "DISCOVERY_ONLY"


def universe_metrics(*, root: Path | str | None = None) -> dict[str, Any]:
    root = _root(root)
    universe, store, by_sym = _load(root)
    rows = list(by_sym.values())
    material = [r for r in rows if r.get("material")]
    def _c(state: str, pool=None) -> int:
        pool = pool if pool is not None else rows
        return sum(1 for r in pool if r.get("coverage_state") == state)
    return {
        "universe_union": len(rows),
        "material": len(material),
        "current": _c("CURRENT", material),
        "research_required": _c("RESEARCH_REQUIRED", material),
        "stale": _c("STALE", material),
        "conflicted": _c("CONFLICTED", material),
        "insufficient_data": _c("INSUFFICIENT_DATA"),
        "role_unknown": sum(1 for r in material if (r.get("portfolio_role") or {}).get("portfolio_role") == "UNKNOWN"),
        "coverage_pct_material": round(
            (100.0 * _c("CURRENT", material) / len(material)) if material else 0.0, 1
        ),
        "desk": (store.get_current("desk") or {}).get("thesis_version"),
        "authority": "READ_ONLY_ADVISORY",
    }
