"""Pure shared thesis freshness policy; no thesis, broker, UI or provider dependencies.

Extracted unchanged from symbol_thesis_coverage so the canonical research-memory
writer need not import the coverage builder's unrelated API/knowledge-graph path.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
from scripts.lib.portfolio_role import resolve_portfolio_role

STALE_DAYS_DEFAULT = 30


MATERIAL_MEMBERSHIPS = frozenset(
    {
        "HELD",
        "FORMER_HOLDING",
        "REENTRY",
        "OPPORTUNITY",
    }
)


CLASS_SLA_DAYS = {
    "held_income": 14,
    "held_growth_core": 30,
    "held_index_bond": 90,
    "reentry_actionable": 14,
    "watchlist_actionable": 45,
}


INCOME_CRITICAL_TICKERS = frozenset(
    {
        "JEPI",
        "PFLT",
        "CSWC",
        "DIV",
        "DIVI",
        "SCHD",
    }
)


INDEX_BOND_TICKERS = frozenset({"BND"})


REENTRY_READY_STATES = frozenset({"READY", "READY TO REVIEW", "IN_ZONE"})


REENTRY_NEAR_STATES = frozenset({"NEAR", "NEAR ENTRY", "OVERSOLD REVIEW"})


def _sym(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _is_held_rec(universe_rec: Optional[dict[str, Any]]) -> bool:
    rec = universe_rec or {}
    if rec.get("held"):
        return True
    return "HELD" in list(rec.get("memberships") or [])


def _reentry_bucket_from_state(state: Any) -> Optional[str]:
    s = str(state or "").strip().upper()
    if not s:
        return None
    if s in REENTRY_READY_STATES:
        return "READY"
    if s in REENTRY_NEAR_STATES:
        return "NEAR"
    return None


def reentry_actionable_bucket(
    universe_rec: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """READY | NEAR | None. Held names are not reentry-actionable."""
    rec = universe_rec or {}
    if _is_held_rec(rec):
        return None
    extra = extra or {}
    re = rec.get("reentry") if isinstance(rec.get("reentry"), dict) else {}
    for blob in (re, rec, extra):
        if not isinstance(blob, dict):
            continue
        bucket = _reentry_bucket_from_state(blob.get("intel_state") or blob.get("state") or blob.get("reentry_state"))
        if bucket:
            return bucket
    return None


def _role_name(
    symbol: str,
    universe_rec: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    *,
    root: Path | None = None,
) -> str:
    extra = extra or {}
    rec = universe_rec or {}
    for blob in (extra, rec):
        role = blob.get("portfolio_role")
        if isinstance(role, dict):
            role = role.get("portfolio_role")
        if isinstance(role, str) and role.strip() and role.strip().upper() != "UNKNOWN":
            return role.strip().upper()
    try:
        resolved = resolve_portfolio_role(symbol, universe_rec=rec, root=root)
        return str(resolved.get("portfolio_role") or "UNKNOWN").upper()
    except Exception:
        return "UNKNOWN"


def coverage_class_for(
    symbol: str,
    universe_rec: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    *,
    root: Path | None = None,
) -> str:
    """held_income | held_index_bond | held_growth_core | reentry_actionable | watchlist_actionable | default."""
    s = _sym(symbol)
    rec = universe_rec or {}
    extra = extra or {}
    forced = str(extra.get("coverage_class") or rec.get("coverage_class") or "").strip().lower()
    if forced in CLASS_SLA_DAYS:
        return forced
    if _is_held_rec(rec):
        if s in INDEX_BOND_TICKERS:
            return "held_index_bond"
        if s in INCOME_CRITICAL_TICKERS:
            return "held_income"
        role = _role_name(s, rec, extra, root=root)
        if role == "INCOME":
            return "held_income"
        return "held_growth_core"
    if reentry_actionable_bucket(rec, extra=extra):
        return "reentry_actionable"
    if "WATCHLIST" in list(rec.get("memberships") or []) or rec.get("watchlist"):
        return "watchlist_actionable"
    return "default"


def stale_days_for(
    symbol: str,
    universe_rec: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    *,
    root: Path | None = None,
) -> int:
    """Class SLA days for a symbol. Fallback STALE_DAYS_DEFAULT."""
    klass = coverage_class_for(symbol, universe_rec, extra, root=root)
    return int(CLASS_SLA_DAYS.get(klass, STALE_DAYS_DEFAULT))
