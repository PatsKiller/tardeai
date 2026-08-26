"""cio_advisory_provenance.py — Advisory Desk data-quality + /v3/advisory wiring.

Build compact provenance blocks so expanded cards never force the operator
to reverse-engineer conflicting prices/targets.

Phase 7: actually attach canonical_financial_facts + advisory_provenance on
the /v3/advisory expand payload. Analyst upside must never be labeled
"vs current" when the denominator is a stale provider snapshot.

P0.3: Finviz / external quote older than the current session is STALE and
ignored for CONFLICT vs today's broker MV — after-hours prefer broker mark.

Authority: READ_ONLY_ADVISORY. No broker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

try:
    from scripts.lib.cio_financial_truth_gate import (
        STATE_CONFLICTED,
        STATE_DATA_UNAVAILABLE,
        STATE_STALE,
        STATE_VERIFIED_AS_OF,
        analyst_upside_vs_canonical,
        classify_price_fields,
        dollar_tol,
        parse_ts,
    )
except ImportError:  # pragma: no cover — scripts/ on path without repo root
    from lib.cio_financial_truth_gate import (  # type: ignore
        STATE_CONFLICTED,
        STATE_DATA_UNAVAILABLE,
        STATE_STALE,
        STATE_VERIFIED_AS_OF,
        analyst_upside_vs_canonical,
        classify_price_fields,
        dollar_tol,
        parse_ts,
    )

ADVISORY_PROVENANCE_VERSION = "advisory_provenance_1.2.0"
DATA_CONFLICT_ACTION_SUPPRESSED = "DATA CONFLICT — ACTION SUPPRESSED"

# External quote sources that must not CONFLICT against today's broker MV when stale.
_EXTERNAL_QUOTE_SOURCE_TOKENS = (
    "finviz",
    "yahoo",
    "provider",
    "enrichment",
    "quote_cache",
    "ticker_enrichment",
)

# Recommendation tokens we treat as an explicit desk response (not absence).
_EXPLICIT_STANCE_TOKENS = frozenset({
    "ADD", "HOLD", "TRIM", "EXIT", "WAIT", "AVOID", "RE_ENTER",
    "INSUFFICIENT_DATA", "BUY", "SELL", "UNDERPERFORM", "OVERWEIGHT",
    "UNDERWEIGHT", "EQUALWEIGHT", "EQUAL_WEIGHT", "STRONG BUY", "STRONG SELL",
})
_MISSING_STANCE_TOKENS = frozenset({
    "", "NONE", "NULL", "N/A", "NA", "UNKNOWN", "MISSING", "-", "—",
})


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def _explicit_stance(value: Any) -> Optional[str]:
    """Return an explicit desk stance, or None when the opinion is missing.

    Missing / blank / 'unknown' is NOT HOLD.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    u = s.upper().replace("-", "_")
    if u in _MISSING_STANCE_TOKENS:
        return None
    # Accept "maria — HOLD" / "HOLD (0.6)" shapes
    for tok in _EXPLICIT_STANCE_TOKENS:
        if u == tok or u.startswith(tok + " ") or u.startswith(tok + "_") or u.endswith(" " + tok):
            return tok if tok != "STRONG BUY" else "ADD"
    # First token if it is a known verdict
    first = u.split()[0].rstrip(":—,.")
    if first in _EXPLICIT_STANCE_TOKENS:
        return first
    return u if u in _EXPLICIT_STANCE_TOKENS else None


def _shares(row: dict[str, Any]) -> Optional[float]:
    return _f(row.get("shares") if row.get("shares") is not None else row.get("quantity"))


def _basis(row: dict[str, Any]) -> Optional[float]:
    return _f(
        row.get("cost_basis")
        if row.get("cost_basis") is not None
        else row.get("total_cost_basis") or row.get("adjusted_cost") or row.get("average_cost")
    )


def _mark_as_of(row: dict[str, Any]) -> Optional[str]:
    v = (
        row.get("price_as_of")
        or row.get("quote_time")
        or row.get("updated_at")
        or row.get("as_of")
    )
    return str(v) if v not in (None, "") else None


def _mark_source(row: dict[str, Any], price_info: dict[str, Any]) -> str:
    return str(
        row.get("price_source")
        or price_info.get("canonical_price_key")
        or row.get("source")
        or "holdings"
    )


def _is_external_quote_source(source: str | None) -> bool:
    src = str(source or "").lower()
    return any(tok in src for tok in _EXTERNAL_QUOTE_SOURCE_TOKENS)


def external_quote_stale_vs_session(
    source: str | None,
    as_of: Any,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """True when an external quote observation is older than today's session date.

    After-hours / next-day broker MV must not be labeled CONFLICTED against a
    Finviz print from a prior session — that print is STALE and ignored.
    """
    if not _is_external_quote_source(source):
        return False
    dt = parse_ts(as_of)
    if dt is None:
        return False
    try:
        from scripts.lib.cio_market_session import get_market_session
    except ImportError:  # pragma: no cover
        from lib.cio_market_session import get_market_session  # type: ignore
    sess = get_market_session(now)
    session_date_s = sess.get("session_date")
    if not session_date_s:
        return False
    try:
        from datetime import date as _date
        session_date = _date.fromisoformat(str(session_date_s))
    except ValueError:
        return False
    # Compare in exchange-local calendar day when possible
    try:
        from zoneinfo import ZoneInfo
        et = ZoneInfo("America/New_York")
        obs_date = dt.astimezone(et).date()
    except Exception:
        obs_date = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).date()
    return obs_date < session_date


def _session_prefers_broker_mark(now: Optional[datetime] = None) -> bool:
    """After RTH (POST/CLOSED) prefer latest broker mark over external prints."""
    try:
        from scripts.lib.cio_market_session import get_market_session
    except ImportError:  # pragma: no cover
        from lib.cio_market_session import get_market_session  # type: ignore
    state = str((get_market_session(now) or {}).get("state") or "").upper()
    return state in {"POST", "CLOSED"}


def build_canonical_financial_facts(
    row: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Structured current-mark facts for the expanded advisory row.

    Operator fields (in display order):
      Current mark, As of, Source, Shares, Market value, Total cost basis,
      Avg cost/share, Unrealized P/L, Quality.

    P0.3: stale Finviz / external quote vs today's broker MV is STALE (ignored
    for CONFLICT), not CONFLICTED. After-hours prefer broker implied mark.
    """
    shares = _shares(row)
    price_info = classify_price_fields(row)
    px = price_info.get("canonical_price")
    mv = _f(row.get("market_value"))
    basis = _basis(row)
    avg = _f(row.get("avg_cost_per_share") or row.get("average_cost") or row.get("avg_cost"))
    if avg is None and shares and shares > 0 and basis is not None:
        # If basis looks like a per-share number (small vs MV), keep it; else divide.
        if mv is not None and basis > 0 and basis < (mv * 0.05) and shares > 1:
            avg = basis  # already per-share
        else:
            avg = basis / shares

    as_of = _mark_as_of(row)
    source = _mark_source(row, price_info)
    implied_px = _f(price_info.get("implied_price_from_mv"))
    broker_px = _f(row.get("broker_position_price") or row.get("broker_price"))
    external_stale = external_quote_stale_vs_session(source, as_of, now=now)
    prefer_broker = _session_prefers_broker_mark(now) or external_stale

    stale_notes: list[str] = []
    if external_stale:
        stale_notes.append(
            f"external quote source={source} as_of={as_of} older than session — STALE, ignored for CONFLICT"
        )
        # Prefer latest broker mark / implied-from-MV over the stale Finviz print
        if broker_px is not None and broker_px > 0:
            px = broker_px
            source = "broker_position_price"
            as_of = str(row.get("broker_position_as_of") or as_of or "")
        elif implied_px is not None and implied_px > 0:
            px = implied_px
            source = "broker_implied_from_mv"
    elif prefer_broker and _is_external_quote_source(source):
        # After-hours: prefer broker mark even if external stamp is same calendar day
        if broker_px is not None and broker_px > 0:
            px = broker_px
            source = "broker_position_price"
            as_of = str(row.get("broker_position_as_of") or as_of or "")
            stale_notes.append("after-hours: preferred broker mark over external quote")
        elif implied_px is not None and implied_px > 0:
            # Only switch when external disagrees materially with broker MV
            if px is None or (px > 0 and abs(implied_px - px) / px > 0.002):
                px = implied_px
                source = "broker_implied_from_mv"
                stale_notes.append("after-hours: preferred broker implied-from-MV over external quote")

    implied = (shares * px) if (shares is not None and px is not None) else None
    upl = (mv - basis) if (mv is not None and basis is not None) else None
    upl_pct = (upl / basis * 100.0) if (upl is not None and basis and basis > 0) else None

    conflicts: list[str] = []
    prices = price_info.get("genuine_marks") or price_info.get("prices") or {}
    # Dual genuine marks / MV arithmetic only conflict when the external print
    # is still treated as current. Session-stale Finviz is ignored.
    if not external_stale:
        if price_info.get("conflicted"):
            conflicts.append(f"Dual price fields disagree: {prices}")
        if implied_px is not None and px is not None and px > 0:
            if abs(implied_px - px) / px > 0.002:
                conflicts.append(
                    f"canonical mark ({px:.2f}) ≠ implied-from-MV ({implied_px:.2f})"
                )
        if implied is not None and mv is not None:
            if abs(implied - mv) > dollar_tol(mv):
                conflicts.append(
                    f"shares×price ({implied:.2f}) ≠ market_value ({mv:.2f})"
                )

    quality = STATE_VERIFIED_AS_OF
    if px is None and mv is None:
        quality = STATE_DATA_UNAVAILABLE
    elif px is None:
        quality = STATE_DATA_UNAVAILABLE
    if external_stale and not conflicts:
        quality = STATE_STALE
    if conflicts:
        quality = STATE_CONFLICTED

    action_suppressed = quality == STATE_CONFLICTED
    return {
        "current_mark": px,
        "current_mark_display": f"${px:,.2f}" if px is not None else "—",
        "as_of": as_of,
        "source": source,
        "shares": shares,
        "market_value": mv,
        "market_value_display": f"${mv:,.2f}" if mv is not None else "—",
        "total_cost_basis": basis,
        "total_cost_basis_display": f"${basis:,.2f}" if basis is not None else "—",
        "avg_cost_per_share": round(avg, 4) if avg is not None else None,
        "avg_cost_per_share_display": f"${avg:,.2f}" if avg is not None else "—",
        "unrealized_pl": round(upl, 2) if upl is not None else None,
        "unrealized_pl_pct": round(upl_pct, 2) if upl_pct is not None else None,
        "unrealized_pl_display": (
            f"${upl:,.2f} / {upl_pct:+.2f}%"
            if upl is not None and upl_pct is not None
            else ("—" if upl is None else f"${upl:,.2f}")
        ),
        "quality": quality,
        "implied_market_value": round(implied, 2) if implied is not None else None,
        "implied_price_from_mv": implied_px,
        "price_fields": prices,
        "price_field_role": price_info.get("price_field_role"),
        "canonical_price_key": price_info.get("canonical_price_key"),
        "conflicts": conflicts,
        "stale_notes": stale_notes,
        "external_quote_stale_vs_session": external_stale,
        "action_suppressed": action_suppressed,
        "banner": DATA_CONFLICT_ACTION_SUPPRESSED if action_suppressed else None,
        "authority": "READ_ONLY_ADVISORY",
    }


def build_analyst_provenance_fields(
    row: dict[str, Any],
    facts: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Analyst target + two upsides: vs canonical current, vs provider snapshot.

    NEVER labels a stale provider denominator as "vs current".
    ``target_vs_current_pct`` is populated only when the denominator *is*
    the canonical current mark.
    """
    facts = facts or {}
    target = _f(
        row.get("analyst_target")
        or row.get("target")
        or row.get("target_price")
        or row.get("consensus_target")
        or row.get("price_target_mean")
    )
    target_as_of = (
        row.get("target_as_of")
        or row.get("analyst_as_of")
        or row.get("as_of")
    )
    if target_as_of not in (None, ""):
        target_as_of = str(target_as_of)
    else:
        target_as_of = None

    snap = _f(
        row.get("analyst_snapshot_price")
        or row.get("provider_ref_price")
        or row.get("provider_snapshot_price")
    )
    snap_as_of = row.get("analyst_snapshot_as_of") or row.get("denominator_as_of") or target_as_of
    if snap_as_of not in (None, ""):
        snap_as_of = str(snap_as_of)
    else:
        snap_as_of = None

    px = facts.get("current_mark")
    if px is None:
        px = classify_price_fields(row).get("canonical_price")

    vs_current: Optional[float] = None
    vs_snap: Optional[float] = None
    if target is not None and px is not None and px > 0:
        vs_current = round((target - px) / px * 100.0, 2)
    if target is not None and snap is not None and snap > 0:
        vs_snap = round((target - snap) / snap * 100.0, 2)

    labeled = analyst_upside_vs_canonical(
        analyst_target=target,
        canonical_price=px,
        analyst_snapshot_price=snap,
    )
    denom_is_current = labeled.get("label") == "upside_vs_canonical_current_price"
    # If provider snapshot is absent, the labeled denom is canonical current.
    if snap is None and px is not None and target is not None:
        denom_is_current = True

    if denom_is_current:
        denom = px
        denom_as_of = facts.get("as_of") or _mark_as_of(row)
        upside_label = "upside_vs_canonical_current_price"
    elif snap is not None:
        denom = snap
        denom_as_of = snap_as_of
        upside_label = "upside_vs_provider_snapshot"
    else:
        denom = labeled.get("denominator_price")
        denom_as_of = snap_as_of
        upside_label = labeled.get("label") or "DATA_UNAVAILABLE"

    quality = labeled.get("quality") or STATE_DATA_UNAVAILABLE
    if snap is not None and px is not None and not denom_is_current:
        quality = STATE_CONFLICTED

    # Honest legacy field: only when the denominator really is current.
    target_vs_current_pct = vs_current if denom_is_current else None

    return {
        "target": target,
        "target_as_of": target_as_of,
        "target_upside_vs_current": vs_current,
        "target_upside_vs_provider_snapshot": vs_snap,
        "denominator_price": denom,
        "denominator_as_of": denom_as_of,
        "denominator_is_canonical_current": bool(denom_is_current),
        "upside_label": upside_label,
        "quality": quality,
        "note": labeled.get("note"),
        "target_vs_current_pct": target_vs_current_pct,
        "price_target_mean": target,
        "as_of": target_as_of,
        "provider_snapshot_price": snap,
        "provider_snapshot_as_of": snap_as_of,
    }


def _stances_from_evidence(row: dict[str, Any]) -> dict[str, Optional[str]]:
    maria = _explicit_stance(row.get("maria_stance") or row.get("fundamental_stance"))
    guardian = _explicit_stance(row.get("guardian_stance") or row.get("risk_stance"))
    items: list[Any] = []
    eb = row.get("evidence_bundle") or {}
    if isinstance(eb, dict):
        items.extend(eb.get("evidence_items") or [])
    expand = row.get("expand") or {}
    if isinstance(expand, dict):
        items.extend(expand.get("evidence_items") or [])
    for it in items:
        if not isinstance(it, dict) or it.get("type") != "agent_opinion":
            continue
        rec = _explicit_stance(it.get("recommendation"))
        if rec is None:
            continue
        agent = str(it.get("agent") or "").lower()
        if "maria" in agent or "fundamental" in agent:
            maria = maria or rec
        elif "guardian" in agent or agent in ("risk", "risk_desk"):
            guardian = guardian or rec
    return {"maria": maria, "guardian": guardian}


def synthesize_specialist_opinions(row: dict[str, Any]) -> Optional[str]:
    """Opinion synthesis. Missing opinion is NOT HOLD.

    Only say desks remain HOLD when explicit current desk responses exist.
    """
    det = _explicit_stance(
        row.get("deterministic_stance") or row.get("stance_code") or row.get("cio_stance")
        or row.get("verdict")
    )
    desks = _stances_from_evidence(row)
    maria = desks["maria"]
    guardian = desks["guardian"]

    explicit_holds = [n for n, s in (("Maria", maria), ("Guardian", guardian)) if s == "HOLD"]
    missing = [n for n, s in (("Maria", maria), ("Guardian", guardian)) if s is None]

    if det != "TRIM":
        if missing and not explicit_holds:
            return None
        return None

    if explicit_holds and not missing:
        return (
            "Fundamental desks remain HOLD. The trim signal is portfolio-risk driven, "
            "not thesis deterioration."
        )
    if explicit_holds and missing:
        return (
            f"{' and '.join(explicit_holds)} explicitly HOLD. "
            f"{' and '.join(missing)} opinion is missing — missing opinion is not HOLD. "
            "The trim signal is portfolio-risk driven, not thesis deterioration."
        )
    return (
        "Trim is portfolio-risk driven. Specialist desk opinions are missing — "
        "missing opinion is not HOLD."
    )


def build_expanded_row_provenance(row: dict[str, Any]) -> dict[str, Any]:
    """Ordered provenance for one advisory/holdings expanded row."""
    facts = build_canonical_financial_facts(row)
    px = facts.get("current_mark")
    shares = facts.get("shares")
    mv = facts.get("market_value")
    basis = facts.get("total_cost_basis")
    upl = facts.get("unrealized_pl")
    upl_pct = facts.get("unrealized_pl_pct")
    analyst_fields = build_analyst_provenance_fields(row, facts)
    analyst_target = analyst_fields.get("target")
    analyst_as_of = analyst_fields.get("target_as_of")

    conflicts = list(facts.get("conflicts") or [])
    if analyst_fields.get("quality") == STATE_CONFLICTED:
        msg = "Analyst upside uses a different denominator than canonical current price"
        if msg not in conflicts:
            conflicts.append(msg)
    if conflicts and DATA_CONFLICT_ACTION_SUPPRESSED not in conflicts:
        conflicts.insert(0, DATA_CONFLICT_ACTION_SUPPRESSED)

    det = str(row.get("deterministic_stance") or row.get("stance_code") or row.get("cio_stance") or "")
    desks = _stances_from_evidence(row)
    synthesis = synthesize_specialist_opinions(row)

    labeled_upside = (
        analyst_fields.get("target_upside_vs_current")
        if analyst_fields.get("denominator_is_canonical_current")
        else analyst_fields.get("target_upside_vs_provider_snapshot")
    )
    fact_list = [
        {
            "label": "Current price",
            "value": px,
            "display": facts.get("current_mark_display") or "—",
            "as_of": facts.get("as_of"),
            "source": facts.get("source"),
        },
        {
            "label": "Position value",
            "value": mv,
            "display": facts.get("market_value_display") or "—",
            "as_of": facts.get("as_of"),
            "source": (
                f"calculated from {shares:g} × ${px:.2f}" if shares and px else "holdings.market_value"
            ),
        },
        {
            "label": "Cost basis",
            "value": basis,
            "display": facts.get("total_cost_basis_display") or "—",
            "as_of": row.get("basis_as_of") or row.get("last_reconciled_at"),
            "source": row.get("cost_basis_source") or "broker/lots",
        },
        {
            "label": "Unrealized gain",
            "value": upl,
            "display": facts.get("unrealized_pl_display") or "—",
            "source": "market_value − cost_basis",
        },
        {
            "label": "Analyst target",
            "value": analyst_target,
            "display": f"${analyst_target:,.2f}" if analyst_target is not None else "—",
            "as_of": analyst_as_of,
            "source": "analyst_consensus",
        },
        {
            "label": analyst_fields.get("upside_label") or "Upside",
            "value": labeled_upside,
            "display": (
                f"{labeled_upside:+.2f}%" if labeled_upside is not None else "—"
            ),
            "source": f"target vs {analyst_fields.get('denominator_price')}",
            "quality": analyst_fields.get("quality"),
            "note": analyst_fields.get("note"),
        },
    ]

    return {
        "version": ADVISORY_PROVENANCE_VERSION,
        "symbol": row.get("symbol"),
        "order": [
            "decision",
            "current_financial_facts",
            "portfolio_role",
            "price_trend",
            "analyst_research",
            "specialist_opinions",
            "conflicts",
            "evidence_provenance",
            "operator_actions",
        ],
        "current_financial_facts": fact_list,
        "canonical_financial_facts": facts,
        "analyst": analyst_fields,
        "conflicts": conflicts,
        "opinion_synthesis": synthesis,
        "specialist_opinions": {
            "deterministic": det or None,
            "maria_or_fundamental": desks.get("maria"),
            "guardian_or_risk": desks.get("guardian"),
            "missing_is_not_hold": True,
        },
        "price_fields": facts.get("price_fields") or {},
        "action_suppressed": bool(facts.get("action_suppressed") or conflicts),
        "banner": DATA_CONFLICT_ACTION_SUPPRESSED if conflicts else None,
        "authority": "READ_ONLY_ADVISORY",
    }


def _merge_holdings_into_row(row: dict[str, Any], holdings: dict[str, Any]) -> dict[str, Any]:
    """Overlay holdings arithmetic without letting a stale analyst quote win."""
    merged = dict(row)
    # Never treat provider snapshot `current_price` as the holdings mark.
    for k in (
        "shares",
        "quantity",
        "market_value",
        "cost_basis",
        "adjusted_cost",
        "average_cost",
        "avg_cost",
        "avg_cost_per_share",
        "price",
        "current_price",
        "last",
        "mark",
        "close",
        "as_of",
        "updated_at",
        "price_as_of",
        "quote_time",
        "price_source",
        "cost_basis_source",
        "basis_as_of",
        "last_reconciled_at",
        "account",
        "symbol",
    ):
        if holdings.get(k) is not None and holdings.get(k) != "":
            merged[k] = holdings[k]
    return merged


def _merge_analyst_into_row(row: dict[str, Any], analyst: dict[str, Any]) -> dict[str, Any]:
    """Copy analyst target/snapshot fields. Do NOT copy analyst.current_price
    onto the holdings mark — that is the stale Yahoo snapshot."""
    merged = dict(row)
    target = analyst.get("target") or analyst.get("price_target_mean") or analyst.get("target_price")
    if target is not None:
        merged["analyst_target"] = target
        merged.setdefault("price_target_mean", target)
        merged.setdefault("target", target)
    as_of = analyst.get("target_as_of") or analyst.get("as_of") or analyst.get("snapshot_date")
    if as_of:
        merged["analyst_as_of"] = as_of
        merged.setdefault("target_as_of", as_of)
    snap = (
        analyst.get("provider_snapshot_price")
        or analyst.get("analyst_snapshot_price")
        or analyst.get("provider_ref_price")
        # Yahoo history column is named current_price but is the snapshot print.
        or analyst.get("snapshot_price")
    )
    if snap is not None:
        merged["analyst_snapshot_price"] = snap
        merged["provider_ref_price"] = snap
        merged["provider_snapshot_price"] = snap
    snap_as_of = analyst.get("provider_snapshot_as_of") or analyst.get("denominator_as_of") or as_of
    if snap_as_of:
        merged["analyst_snapshot_as_of"] = snap_as_of
    for passthrough in (
        "consensus_rating",
        "recommendation_mean",
        "analyst_count",
        "price_target_high",
        "price_target_low",
        "source",
    ):
        if analyst.get(passthrough) is not None and merged.get(passthrough) is None:
            merged[passthrough] = analyst[passthrough]
    return merged


def attach_expand_provenance(
    row: dict[str, Any],
    *,
    holdings: Optional[dict[str, Any]] = None,
    analyst: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Attach expand.canonical_financial_facts + expand.advisory_provenance.

    Mutates and returns ``row``. Safe on incomplete mock rows.
    """
    merged = dict(row)
    if holdings:
        merged = _merge_holdings_into_row(merged, holdings)
    if analyst:
        merged = _merge_analyst_into_row(merged, analyst)

    provenance = build_expanded_row_provenance(merged)
    facts = provenance.get("canonical_financial_facts") or build_canonical_financial_facts(merged)
    analyst_fields = provenance.get("analyst") or build_analyst_provenance_fields(merged, facts)

    analyst_out = dict(analyst or {})
    analyst_out.update(analyst_fields)
    if not analyst_out.get("denominator_is_canonical_current"):
        analyst_out["target_vs_current_pct"] = None

    expand = dict(row.get("expand") or {})
    pa = dict(expand.get("price_action") or row.get("price_action") or {})
    if pa or facts.get("current_mark") is not None:
        if facts.get("current_mark") is not None:
            pa.setdefault("current_mark", facts.get("current_mark"))
        if facts.get("as_of") and not pa.get("as_of"):
            pa["as_of"] = facts.get("as_of")
        if facts.get("source") and not pa.get("source"):
            pa["source"] = facts.get("source")
        expand["price_action"] = pa

    expand["canonical_financial_facts"] = facts
    expand["advisory_provenance"] = provenance
    expand["analyst"] = analyst_out

    row.update({
        k: merged[k]
        for k in (
            "shares", "current_price", "price", "market_value", "cost_basis",
            "as_of", "updated_at", "price_source", "average_cost",
            "analyst_target", "analyst_as_of", "analyst_snapshot_price",
            "provider_ref_price", "provider_snapshot_price",
        )
        if k in merged and merged[k] is not None
    })
    row["canonical_financial_facts"] = facts
    row["advisory_provenance"] = provenance
    row["expand"] = expand

    dq = dict(row.get("data_quality") or {})
    if facts.get("conflicts") or provenance.get("conflicts"):
        dq["conflicts"] = list(facts.get("conflicts") or []) + [
            c for c in (provenance.get("conflicts") or [])
            if c not in (facts.get("conflicts") or [])
        ]
        dq["quality"] = facts.get("quality") or STATE_CONFLICTED
        dq["action_suppressed"] = True
        dq["banner"] = DATA_CONFLICT_ACTION_SUPPRESSED
    else:
        dq.setdefault("quality", facts.get("quality"))
        dq.setdefault("action_suppressed", False)
    row["data_quality"] = dq
    return row
