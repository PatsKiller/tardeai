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

# Class SLAs — policy-in-code (docs/ops/RESEARCH_LIFECYCLE_STANDARD.md).
# Fallback remains STALE_DAYS_DEFAULT when a name is not in an actionable class.
CLASS_SLA_DAYS = {
    "held_income": 14,
    "held_growth_core": 30,
    "held_index_bond": 90,
    "reentry_actionable": 14,
    "watchlist_actionable": 45,
}

# Income / BDC-like names (held) — 14d. Not a parallel taxonomy; ticker set + INCOME role.
INCOME_CRITICAL_TICKERS = frozenset({
    "JEPI", "PFLT", "CSWC", "DIV", "DIVI", "SCHD",
})
# Bond / index ballast (held) — 90d. BND is the book ballast; do not use DEFENSIVE role
# (that role also covers NOC/LDOS/RTX/BAH).
INDEX_BOND_TICKERS = frozenset({"BND"})

# Reentry desk intel.state → READY/NEAR. Matches reentry_decision_desk.normalize_reentry_s3_status
# without importing that module (broker-backed, heavy).
REENTRY_READY_STATES = frozenset({"READY", "READY TO REVIEW", "IN_ZONE"})
REENTRY_NEAR_STATES = frozenset({"NEAR", "NEAR ENTRY", "OVERSOLD REVIEW"})

AGE_GATE_SHORT_CIRCUIT_KEYS = (
    "catalyst",
    "earnings",
    "dividend",
    "need_data",
)

HELD_SLA_TARGET_PCT = 100.0
ACTIONABLE_SLA_TARGET_PCT = 100.0


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


def _sym(symbol: str) -> str:
    return str(symbol or "").strip().upper()


def _truthy_flag(val: Any) -> bool:
    if val is None or val is False:
        return False
    if val is True:
        return True
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() not in ("", "0", "false", "no", "none", "null")
    if isinstance(val, (list, tuple, set, dict)):
        return len(val) > 0
    return True


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
        bucket = _reentry_bucket_from_state(
            blob.get("intel_state") or blob.get("state") or blob.get("reentry_state")
        )
        if bucket:
            return bucket
    return None


def is_watchlist_actionable(universe_rec: Optional[dict[str, Any]] = None) -> bool:
    """WATCHLIST membership that is material, excluding held and READY/NEAR.

    Does not pull the full T1 (~250) set into a 100% SLA. Discovery-only
    watchlist names stay out.
    """
    rec = universe_rec or {}
    memberships = list(rec.get("memberships") or [])
    if "WATCHLIST" not in memberships:
        return False
    if _is_held_rec(rec):
        return False
    if reentry_actionable_bucket(rec):
        return False
    if set(memberships) & MATERIAL_MEMBERSHIPS:
        return True
    if rec.get("opportunity"):
        return True
    intel = (rec.get("reentry") or {}).get("intel_state") if isinstance(rec.get("reentry"), dict) else None
    return bool(intel)


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


def age_gate_short_circuit_reason(
    universe_rec: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    thesis_extra: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """If catalyst/earnings/dividend/NEED_DATA is flagged, return the token.

    Age-gate short-circuit: do not mark STALE solely by calendar age.
    """
    blobs: list[dict[str, Any]] = []
    for raw in (universe_rec, extra, thesis_extra):
        if isinstance(raw, dict):
            blobs.append(raw)
            nested = raw.get("extra")
            if isinstance(nested, dict):
                blobs.append(nested)
            flags = raw.get("flags")
            if isinstance(flags, dict):
                blobs.append(flags)
    for blob in blobs:
        if _truthy_flag(blob.get("age_gate_short_circuit")):
            token = str(blob.get("age_gate_short_circuit")).strip().lower()
            if token in AGE_GATE_SHORT_CIRCUIT_KEYS:
                return token
            return "catalyst"
        intent = str(blob.get("intent") or blob.get("operator_intent") or "").strip().upper()
        if intent == "NEED_DATA":
            return "need_data"
        for key in AGE_GATE_SHORT_CIRCUIT_KEYS:
            if _truthy_flag(blob.get(key)) or _truthy_flag(blob.get(key.upper())):
                return key
        if _truthy_flag(blob.get("NEED_DATA")) or _truthy_flag(blob.get("operator_need_data")):
            return "need_data"
    return None


def row_is_fresh(row: dict[str, Any], *, sla_days: int | None = None) -> bool:
    """CURRENT and thesis age within class SLA."""
    if str(row.get("coverage_state") or "") != "CURRENT":
        return False
    if not row.get("has_current_symbol_thesis"):
        return False
    age = row.get("thesis_age_days")
    sla = sla_days if sla_days is not None else row.get("sla_days")
    if age is None or sla is None:
        return False
    try:
        return float(age) <= float(sla)
    except (TypeError, ValueError):
        return False


def coverage_fresh_pcts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Always two numbers: coverage_pct (has thesis) and fresh_pct (CURRENT + in SLA)."""
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "has_current_n": 0,
            "fresh_n": 0,
            "coverage_pct": 0.0,
            "fresh_pct": 0.0,
        }
    has_current_n = sum(1 for r in rows if r.get("has_current_symbol_thesis"))
    fresh_n = sum(1 for r in rows if r.get("fresh") or row_is_fresh(r))
    return {
        "n": n,
        "has_current_n": has_current_n,
        "fresh_n": fresh_n,
        "coverage_pct": round(100.0 * has_current_n / n, 2),
        "fresh_pct": round(100.0 * fresh_n / n, 2),
    }


def load_reentry_actionable_map(*, root: Path | None = None) -> dict[str, str]:
    """symbol → READY|NEAR from reentry_decision_desk_latest.json. Excludes held."""
    from scripts.lib.holdings_universe import held_equity_tickers, is_held_equity_ticker

    root = Path(root or ROOT)
    held = set(held_equity_tickers(root=root))
    path = root / "data" / "runtime" / "reentry_decision_desk_latest.json"
    out: dict[str, str] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        s = _sym(r.get("symbol") or r.get("ticker"))
        if not s or s in held or r.get("held") or not is_held_equity_ticker(s):
            continue
        intel = r.get("intel") if isinstance(r.get("intel"), dict) else {}
        bucket = _reentry_bucket_from_state(
            intel.get("state") or r.get("state") or r.get("intel_state")
        )
        if bucket:
            out[s] = bucket
    return out


def actionable_universe_slices(
    *,
    root: Path | None = None,
    universe: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """held ∪ reentry READY/NEAR ∪ watchlist-actionable. Held denominator is equity tickers."""
    from scripts.lib.holdings_universe import held_equity_tickers

    root = Path(root or ROOT)
    held = list(held_equity_tickers(root=root))
    held_set = set(held)
    reentry_map = load_reentry_actionable_map(root=root)
    watch: list[str] = []
    symbols = (universe or {}).get("symbols") or {}
    if isinstance(symbols, dict):
        for raw_sym, rec in symbols.items():
            s = _sym(raw_sym)
            if not s or s in held_set:
                continue
            rec = rec if isinstance(rec, dict) else {}
            bucket = reentry_actionable_bucket(rec)
            if bucket:
                reentry_map.setdefault(s, bucket)
            elif is_watchlist_actionable(rec):
                watch.append(s)
    ready = sorted(s for s, b in reentry_map.items() if b == "READY" and s not in held_set)
    near = sorted(s for s, b in reentry_map.items() if b == "NEAR" and s not in held_set)
    reentry = sorted(set(ready) | set(near))
    return {
        "held": held,
        "reentry_actionable": reentry,
        "reentry_ready": ready,
        "reentry_near": near,
        "reentry_actionable_by_state": {s: reentry_map[s] for s in reentry},
        "watchlist_actionable": sorted(set(watch)),
    }


def _slice_pcts(
    slice_symbols: list[str],
    by_sym: dict[str, dict[str, Any]],
    *,
    sla_target_pct: float = HELD_SLA_TARGET_PCT,
) -> dict[str, Any]:
    rows = [by_sym[s] for s in slice_symbols if s in by_sym]
    # Missing rows count as uncovered / not fresh (denominator is the slice).
    n = len(slice_symbols)
    if n == 0:
        return {
            "n": 0,
            "has_current_n": 0,
            "fresh_n": 0,
            "coverage_pct": 0.0,
            "fresh_pct": 0.0,
            "sla_target_pct": sla_target_pct,
            "sla_met": False,
        }
    has_current_n = 0
    fresh_n = 0
    for s in slice_symbols:
        r = by_sym.get(s) or {}
        if r.get("has_current_symbol_thesis"):
            has_current_n += 1
        if r.get("fresh") or row_is_fresh(r):
            fresh_n += 1
    coverage_pct = round(100.0 * has_current_n / n, 2)
    fresh_pct = round(100.0 * fresh_n / n, 2)
    return {
        "n": n,
        "has_current_n": has_current_n,
        "fresh_n": fresh_n,
        "coverage_pct": coverage_pct,
        "fresh_pct": fresh_pct,
        "sla_target_pct": sla_target_pct,
        "sla_met": coverage_pct >= sla_target_pct and fresh_pct >= sla_target_pct,
        "classified_rows": len(rows),
    }


def classify_symbol(
    symbol: str,
    *,
    universe_rec: dict[str, Any],
    store: CIOThesisStore,
    stale_days: int | None = None,
    root: Path | None = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Classify one symbol's thesis coverage (read-only)."""
    tid = symbol_thesis_id(symbol)
    cur = store.get_current(tid)
    desk = store.get_current("desk")
    extra = extra or {}
    role = resolve_portfolio_role(symbol, universe_rec=universe_rec, thesis_rec=cur, root=root)

    memberships = list(universe_rec.get("memberships") or [])
    material = bool(set(memberships) & MATERIAL_MEMBERSHIPS) or ("WATCHLIST" in memberships and (
        (universe_rec.get("reentry") or {}).get("intel_state")
    ))

    reentry = universe_rec.get("reentry") or {}
    intel_state = (reentry.get("intel_state") or "")
    opp = universe_rec.get("opportunity")
    cov_class = coverage_class_for(symbol, universe_rec, extra, root=root)
    sla_days = int(stale_days) if stale_days is not None else stale_days_for(
        symbol, universe_rec, extra, root=root
    )
    thesis_extra = cur.get("extra") if isinstance((cur or {}).get("extra"), dict) else {}
    sc = age_gate_short_circuit_reason(universe_rec, extra=extra, thesis_extra=thesis_extra)

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
        elif age is not None and age > sla_days and not sc:
            state = "STALE"
            reason = f"symbol_thesis_age_days={age:.1f}>{sla_days}"
            research_gaps.append("Refresh stale symbol thesis with current market/evidence")
        elif len(summary) < 40:
            state = "RESEARCH_REQUIRED"
            reason = "symbol_thesis_too_thin"
            research_gaps.append("Expand living thesis: why owned/watched, invalidation, what changes mind")
        else:
            state = "CURRENT"
            if sc and age is not None and age > sla_days:
                reason = f"age_gate_short_circuit_{sc}"
            else:
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

    age_out = _age_days((cur or {}).get("published_ts") or (cur or {}).get("updated_ts"))
    fresh = (
        state == "CURRENT"
        and bool(cur)
        and age_out is not None
        and age_out <= float(sla_days)
    )

    return {
        "symbol": symbol.upper(),
        "thesis_id": tid,
        "coverage_state": state,
        "coverage_reason": reason,
        "coverage_class": cov_class,
        "sla_days": sla_days,
        "fresh": fresh,
        "age_gate_short_circuit": sc,
        "has_current_symbol_thesis": bool(cur),
        "has_only_desk_thesis": bool(desk) and not bool(cur),
        "thesis_version": (cur or {}).get("thesis_version") or (make_pin(tid, 0) if False else None),
        "thesis_pin": (cur or {}).get("thesis_version"),
        "thesis_age_days": age_out,
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
    stale_days: int | None = None,
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

    pcts = coverage_fresh_pcts(rows)
    by_sym = {r["symbol"]: r for r in rows}
    slices = actionable_universe_slices(root=root, universe=universe)
    slice_reports = {
        "held": _slice_pcts(slices["held"], by_sym, sla_target_pct=HELD_SLA_TARGET_PCT),
        "reentry_actionable": _slice_pcts(
            slices["reentry_actionable"], by_sym, sla_target_pct=ACTIONABLE_SLA_TARGET_PCT
        ),
        "watchlist_actionable": _slice_pcts(
            slices["watchlist_actionable"], by_sym, sla_target_pct=ACTIONABLE_SLA_TARGET_PCT
        ),
    }
    slice_reports["held"]["symbols"] = list(slices["held"])
    slice_reports["reentry_actionable"]["symbols"] = list(slices["reentry_actionable"])
    slice_reports["reentry_actionable"]["ready"] = list(slices["reentry_ready"])
    slice_reports["reentry_actionable"]["near"] = list(slices["reentry_near"])
    slice_reports["watchlist_actionable"]["symbols"] = list(slices["watchlist_actionable"])

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "coverage_pct": pcts["coverage_pct"],
        "fresh_pct": pcts["fresh_pct"],
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
            "fresh": pcts["fresh_n"],
            "rows": len(rows),
        },
        "slices": slice_reports,
        "desk": store.get_current("desk"),
        "rows": rows,
        "universe_errors": universe.get("errors") or [],
    }


def build_actionable_coverage_report(
    *,
    root: Path | None = None,
    store: CIOThesisStore | None = None,
) -> dict[str, Any]:
    """READY/NEAR (+ watchlist-actionable slice). Never mixes into held_count.

    Fail-soft: missing desk/store yields empty slices, not an exception.
    """
    root = Path(root or ROOT)
    try:
        universe = reconcile_universe(root)
    except Exception:
        universe = {"symbols": {}, "counts": {}, "errors": ["reconcile_failed"]}
    try:
        store = store or CIOThesisStore(
            event_path=root / "data/cio/cio_theses.jsonl",
            projection_path=root / "data/cio/cio_theses_projection.json",
        )
    except Exception:
        store = None
    slices = actionable_universe_slices(root=root, universe=universe)
    symbols_map = (universe.get("symbols") or {}) if isinstance(universe, dict) else {}
    rows: list[dict[str, Any]] = []
    if store is not None:
        # READY/NEAR only — do not fan out T1 watchlist into this sibling report.
        for s in slices["reentry_actionable"]:
            rec = symbols_map.get(s) if isinstance(symbols_map, dict) else None
            bucket = slices["reentry_actionable_by_state"].get(s)
            if not isinstance(rec, dict):
                rec = {
                    "memberships": ["REENTRY"],
                    "held": False,
                    "reentry": {
                        "intel_state": "READY TO REVIEW" if bucket == "READY" else "NEAR ENTRY",
                    },
                }
            try:
                rows.append(classify_symbol(s, universe_rec=rec, store=store, root=root))
            except Exception:
                continue
    by_sym = {r["symbol"]: r for r in rows}
    reentry_pcts = _slice_pcts(
        slices["reentry_actionable"], by_sym, sla_target_pct=ACTIONABLE_SLA_TARGET_PCT
    )
    watch_n = len(slices["watchlist_actionable"])
    watch_pcts = {
        "n": watch_n,
        "has_current_n": None,
        "fresh_n": None,
        "coverage_pct": None,
        "fresh_pct": None,
        "sla_target_pct": ACTIONABLE_SLA_TARGET_PCT,
        "note": "membership slice only; not mixed into held_count or reentry coverage_pct",
    }
    return {
        "schema": "ActionableThesisCoverage@v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "authority": "READ_ONLY_ADVISORY",
        "coverage_pct": reentry_pcts["coverage_pct"],
        "fresh_pct": reentry_pcts["fresh_pct"],
        "sla_target_pct": ACTIONABLE_SLA_TARGET_PCT,
        "sla_met": reentry_pcts["sla_met"],
        "reentry_actionable_n": reentry_pcts["n"],
        "reentry_ready": list(slices["reentry_ready"]),
        "reentry_near": list(slices["reentry_near"]),
        "watchlist_actionable_n": watch_pcts["n"],
        "watchlist_actionable": watch_pcts,
        "reentry_actionable": reentry_pcts,
        "rows": rows,
        "root": str(root),
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
