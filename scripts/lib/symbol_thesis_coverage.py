"""Per-symbol living thesis coverage over CIOThesisStore (READ_ONLY_ADVISORY).

Coverage contract — every ACTIVE/MATERIAL symbol resolves to one of:
  CURRENT | RESEARCH_REQUIRED | STALE | CONFLICTED | RETIRED | INSUFFICIENT_DATA

There is never an unexplained NO RECORD for material symbols.

Does NOT invent a parallel store. Uses thesis_id = symbol_<ticker_lower>.
Default production path remains desk@vN; this module adds symbol coverage discipline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional

from scripts.lib.cio_theses import CIOThesisStore, make_pin
from scripts.lib.portfolio_role import resolve_portfolio_role
from scripts.lib.symbol_universe import reconcile_universe, MEMBERSHIPS

ROOT = Path(__file__).resolve().parents[2]

COVERAGE_STATES = (
    "CURRENT",
    "RESEARCH_REQUIRED",
    "STALE",
    "CONFLICTED",
    "RETIRED",
    "INSUFFICIENT_DATA",
)

STALE_DAYS_DEFAULT = 30
MATERIAL_MEMBERSHIPS = frozenset({
    "HELD", "FORMER_HOLDING", "REENTRY", "OPPORTUNITY",
})


def symbol_thesis_id(symbol: str) -> str:
    s = str(symbol or "").strip().lower()
    s = "".join(ch if ch.isalnum() or ch in "_-" else "" for ch in s)
    if not s:
        raise ValueError("empty symbol")
    if s[0].isdigit():
        s = "s_" + s
    return f"symbol_{s}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _age_days(ts: Any) -> Optional[float]:
    dt = _parse_ts(ts)
    if not dt:
        return None
    return (_now() - dt).total_seconds() / 86400.0


def classify_symbol(
    symbol: str,
    *,
    universe_rec: dict[str, Any],
    store: CIOThesisStore,
    stale_days: int = STALE_DAYS_DEFAULT,
    root: Path | None = None,
) -> dict[str, Any]:
    """Classify one symbol's thesis coverage (read-only)."""
    tid = symbol_thesis_id(symbol)
    cur = store.get_current(tid)
    desk = store.get_current("desk")
    role = resolve_portfolio_role(symbol, universe_rec=universe_rec, thesis_rec=cur, root=root)

    memberships = list(universe_rec.get("memberships") or [])
    material = bool(set(memberships) & MATERIAL_MEMBERSHIPS) or ("WATCHLIST" in memberships and (
        (universe_rec.get("reentry") or {}).get("intel_state")
    ))

    reentry = universe_rec.get("reentry") or {}
    intel_state = (reentry.get("intel_state") or "")
    opp = universe_rec.get("opportunity")

    research_gaps: list[str] = []
    state = "INSUFFICIENT_DATA"
    reason = "no_symbol_thesis"

    if cur and (cur.get("status") or "active") == "archived":
        state = "RETIRED"
        reason = "symbol_thesis_archived"
    elif cur:
        age = _age_days(cur.get("published_ts") or cur.get("updated_ts"))
        summary = (cur.get("summary") or "").strip()
        extra_gaps = cur.get("research_gaps") or (cur.get("extra") or {}).get("research_gaps") or []
        if isinstance(extra_gaps, list):
            research_gaps.extend(str(x) for x in extra_gaps)
        # Conflict: held vs retired stance, etc.
        stance = (cur.get("stance") or "").lower()
        if universe_rec.get("held") and stance in ("avoid", "retired", "do_not_reenter"):
            state = "CONFLICTED"
            reason = "held_but_avoid_stance"
            research_gaps.append("Resolve conflict: currently held but thesis stance is avoid/retired")
        elif age is not None and age > stale_days:
            state = "STALE"
            reason = f"symbol_thesis_age_days={age:.1f}>{stale_days}"
            research_gaps.append("Refresh stale symbol thesis with current market/evidence")
        elif len(summary) < 40:
            state = "RESEARCH_REQUIRED"
            reason = "symbol_thesis_too_thin"
            research_gaps.append("Expand living thesis: why owned/watched, invalidation, what changes mind")
        else:
            state = "CURRENT"
            reason = "symbol_thesis_fresh"
    else:
        # No symbol thesis
        if not material and "WATCHLIST" in memberships and not opp:
            state = "INSUFFICIENT_DATA"
            reason = "watchlist_only_no_symbol_thesis"
            research_gaps.append("Optional: create symbol thesis if this watchlist name becomes material")
        else:
            state = "RESEARCH_REQUIRED"
            reason = "missing_symbol_thesis"
            research_gaps.append("Create living symbol thesis (role, why owned/exited, invalidation, research gaps)")

    if role.get("role_research_required"):
        research_gaps.append("Portfolio role UNKNOWN — gather operator/historical role evidence")

    # Re-entry mechanical fields are NOT a thesis — flag gap when reentry present without thesis
    if "REENTRY" in memberships and not cur:
        research_gaps.append(
            "Re-entry desk has decision-control fields only; need investment thesis (why exit, thesis intact?, market fit)"
        )

    # Dedup gaps
    seen = set()
    gaps = []
    for g in research_gaps:
        if g not in seen:
            seen.add(g)
            gaps.append(g)

    return {
        "symbol": symbol.upper(),
        "thesis_id": tid,
        "coverage_state": state,
        "coverage_reason": reason,
        "has_current_symbol_thesis": bool(cur),
        "has_only_desk_thesis": bool(desk) and not bool(cur),
        "thesis_version": (cur or {}).get("thesis_version") or (make_pin(tid, 0) if False else None),
        "thesis_pin": (cur or {}).get("thesis_version"),
        "thesis_age_days": _age_days((cur or {}).get("published_ts") or (cur or {}).get("updated_ts")),
        "thesis_status": (cur or {}).get("status"),
        "thesis_summary": ((cur or {}).get("summary") or "")[:400] or None,
        "thesis_stance": (cur or {}).get("stance") or None,
        "desk_pin": (desk or {}).get("thesis_version"),
        "desk_stance": (desk or {}).get("stance"),
        "portfolio_role": role,
        "memberships": memberships,
        "reentry_state": intel_state or None,
        "reentry_advisory_action": reentry.get("advisory_action"),
        "opportunity_rank": (opp or {}).get("rank") if opp else None,
        "research_gaps": gaps,
        "research_required": state in ("RESEARCH_REQUIRED", "STALE", "CONFLICTED") or bool(gaps),
        "material": bool(material or opp or universe_rec.get("held")),
        "authority": "READ_ONLY_ADVISORY",
    }


def build_coverage_report(
    *,
    root: Path | None = None,
    store: CIOThesisStore | None = None,
    stale_days: int = STALE_DAYS_DEFAULT,
    material_only: bool = False,
) -> dict[str, Any]:
    root = Path(root or ROOT)
    universe = reconcile_universe(root)
    store = store or CIOThesisStore(
        # default paths resolve relative to CWD; prefer production data via symlink/.env root
        event_path=root / "data/cio/cio_theses.jsonl",
        projection_path=root / "data/cio/cio_theses_projection.json",
    )
    rows = []
    for sym, rec in sorted((universe.get("symbols") or {}).items()):
        row = classify_symbol(sym, universe_rec=rec, store=store, stale_days=stale_days, root=root)
        if material_only and not row.get("material"):
            continue
        rows.append(row)

    def _c(state: str) -> int:
        return sum(1 for r in rows if r["coverage_state"] == state)

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "universe_counts": universe.get("counts"),
        "coverage_counts": {
            "CURRENT": _c("CURRENT"),
            "RESEARCH_REQUIRED": _c("RESEARCH_REQUIRED"),
            "STALE": _c("STALE"),
            "CONFLICTED": _c("CONFLICTED"),
            "RETIRED": _c("RETIRED"),
            "INSUFFICIENT_DATA": _c("INSUFFICIENT_DATA"),
            "symbol_thesis": sum(1 for r in rows if r["has_current_symbol_thesis"]),
            "desk_thesis_only": sum(1 for r in rows if r["has_only_desk_thesis"]),
            "missing_symbol_thesis": sum(1 for r in rows if not r["has_current_symbol_thesis"]),
            "role_unknown": sum(1 for r in rows if (r.get("portfolio_role") or {}).get("portfolio_role") == "UNKNOWN"),
            "rows": len(rows),
        },
        "desk": store.get_current("desk"),
        "rows": rows,
        "universe_errors": universe.get("errors") or [],
    }


def research_gap_triggers(report: dict[str, Any], *, limit: int = 50) -> list[dict[str, Any]]:
    """Deterministic research agenda items from coverage (no side effects)."""
    out = []
    for r in report.get("rows") or []:
        if not r.get("research_required"):
            continue
        triggers = []
        if not r.get("has_current_symbol_thesis"):
            triggers.append("missing_thesis")
        if r.get("coverage_state") == "STALE":
            triggers.append("stale_thesis")
        if r.get("coverage_state") == "CONFLICTED":
            triggers.append("contradiction")
        if r.get("reentry_state") and not r.get("has_current_symbol_thesis"):
            triggers.append("reentry_without_thesis")
        if r.get("opportunity_rank") is not None and not r.get("has_current_symbol_thesis"):
            triggers.append("opportunity_without_thesis")
        if (r.get("portfolio_role") or {}).get("role_research_required"):
            triggers.append("role_unknown")
        out.append({
            "symbol": r["symbol"],
            "thesis_id": r["thesis_id"],
            "coverage_state": r["coverage_state"],
            "triggers": triggers,
            "research_gaps": r.get("research_gaps") or [],
            "priority": (
                "HIGH" if r.get("held") or r.get("coverage_state") == "CONFLICTED"
                else "NORMAL"
            ),
            "authority": "READ_ONLY_ADVISORY",
        })
        if len(out) >= limit:
            break
    # sort: HIGH first, then RESEARCH_REQUIRED
    out.sort(key=lambda x: (0 if x["priority"] == "HIGH" else 1, x["symbol"]))
    return out
