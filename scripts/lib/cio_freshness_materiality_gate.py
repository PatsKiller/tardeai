"""cio_freshness_materiality_gate.py — Phase 3 Freshness & Materiality (acceptance).

Nothing may say ACT NOW merely because recommended_delta_usd != 0.

ACT NOW requires:
  * financial-truth gate not CONFLICTED for the symbol / book
  * holdings freshness PASS
  * quote / market-value freshness PASS
  * minimum evidence source count
  * no unresolved contradiction affecting sizing
  * risk trigger considered current when used
  * decision generated/revalidated within horizon

Otherwise labels:
  REVIEW | WATCH | REVALIDATE | DATA_CONFLICT | STALE_REFRESH_REQUIRED

READ_ONLY_ADVISORY. Pure policy — no broker / Telegram.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

# Reuse timestamp helpers from financial truth gate
from scripts.lib.cio_financial_truth_gate import (  # noqa: E402
    STATE_CONFLICTED,
    STATE_DATA_UNAVAILABLE,
    STATE_STALE,
    STATE_VERIFIED_AS_OF,
    STATE_VERIFIED_CURRENT,
    age_seconds,
    parse_ts,
)

FRESHNESS_MATERIALITY_VERSION = "freshness_materiality_1.0.0"

# Operator-facing action labels (Phase 3)
LABEL_ACT_NOW = "ACT_NOW"
LABEL_REVIEW = "REVIEW"
LABEL_WATCH = "WATCH"
LABEL_REVALIDATE = "REVALIDATE"
LABEL_DATA_CONFLICT = "DATA_CONFLICT"
LABEL_STALE_REFRESH = "STALE_REFRESH_REQUIRED"

ACTION_LABELS = frozenset({
    LABEL_ACT_NOW,
    LABEL_REVIEW,
    LABEL_WATCH,
    LABEL_REVALIDATE,
    LABEL_DATA_CONFLICT,
    LABEL_STALE_REFRESH,
})

# Policy thresholds (seconds) — configurable via apply_policy kwargs
QUOTE_FRESH_SEC = 15 * 60          # RTH quote / MV
HOLDINGS_FRESH_SEC = 48 * 3600     # broker snapshot / holdings book
DECISION_REVALIDATE_SEC = 24 * 3600
THESIS_FRESH_SEC = 7 * 24 * 3600
ADVISORY_FRESH_SEC = 7 * 24 * 3600
ANALYST_MAX_AGE_SEC = 90 * 24 * 3600  # may be old but must be dated
SECTOR_FRESH_SEC = 48 * 3600
CASH_FRESH_SEC = 48 * 3600
RISK_FRESH_SEC = 48 * 3600
HERMES_FRESH_SEC = 14 * 24 * 3600
MIN_EVIDENCE_SOURCES_ACT_NOW = 2

_NEUTRAL_WHY = "no new desk signal"


def _fnum(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _session_context(now: datetime) -> dict[str, Any]:
    """Rough US equity session flag (UTC). Not a full calendar."""
    # US RTH ~ 13:30–20:00 UTC (EDT) / 14:30–21:00 (EST) — use 13:30–21:00 window
    hour = now.hour + now.minute / 60.0
    weekday = now.weekday()  # 0=Mon
    is_weekday = weekday < 5
    rth = is_weekday and 13.5 <= hour < 21.0
    return {
        "is_weekday": is_weekday,
        "likely_rth": rth,
        "quote_policy": "rth_15m" if rth else "after_hours_latest_supported",
        "note": (
            "Regular session: quote/MV age <= 15m where live marks exist. "
            "After-hours/weekend: use latest supported mark and label as_of."
            if not rth else
            "Regular session quote freshness window active (15 minutes)."
        ),
    }


def _freshness_record(
    *,
    name: str,
    ts: Any,
    max_age_sec: float,
    now: datetime,
    required_for_act_now: bool,
    source: str = "",
    present: bool = True,
    after_hours_ok: bool = False,
    session: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """One evidence-class freshness evaluation."""
    session = session or {}
    if not present:
        return {
            "name": name,
            "present": False,
            "pass": not required_for_act_now,
            "required_for_act_now": required_for_act_now,
            "quality": STATE_DATA_UNAVAILABLE,
            "age_seconds": None,
            "source_as_of": None,
            "source": source or None,
            "max_age_sec": max_age_sec,
            "detail": "missing",
        }
    dt = parse_ts(ts)
    if dt is None:
        # Present but undated — cannot prove freshness
        return {
            "name": name,
            "present": True,
            "pass": False if required_for_act_now else True,
            "required_for_act_now": required_for_act_now,
            "quality": STATE_DATA_UNAVAILABLE,
            "age_seconds": None,
            "source_as_of": str(ts) if ts else None,
            "source": source or None,
            "max_age_sec": max_age_sec,
            "detail": "undated",
        }
    age = age_seconds(dt, now=now) or 0.0
    # After-hours: quotes may be older than 15m but still "latest supported"
    effective_max = max_age_sec
    detail = "ok"
    if name in ("quote", "market_value") and not session.get("likely_rth") and after_hours_ok:
        effective_max = max(max_age_sec, 24 * 3600)  # allow prior close mark
        detail = "after_hours_latest_supported"
    passed = age <= effective_max
    if not passed:
        quality = STATE_STALE
        detail = "stale"
    else:
        quality = STATE_VERIFIED_CURRENT if age <= max_age_sec else STATE_VERIFIED_AS_OF
    return {
        "name": name,
        "present": True,
        "pass": passed,
        "required_for_act_now": required_for_act_now,
        "quality": quality,
        "age_seconds": round(age, 1),
        "source_as_of": dt.isoformat(),
        "source": source or None,
        "max_age_sec": effective_max,
        "detail": detail,
    }


def collect_evidence_timestamps(
    *,
    decision: dict[str, Any],
    holdings_doc: Optional[dict[str, Any]] = None,
    position_row: Optional[dict[str, Any]] = None,
    financial_truth: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pull best-effort timestamps for each evidence class."""
    extra = extra or {}
    doc = holdings_doc or {}
    pos = position_row or {}
    # holdings book
    holdings_ts = doc.get("updated_at") or doc.get("as_of") or doc.get("generated_at")
    # quote / MV from position or decision
    quote_ts = (
        pos.get("updated_at")
        or pos.get("price_as_of")
        or pos.get("quote_time")
        or pos.get("as_of")
        or decision.get("quote_as_of")
        or decision.get("as_of")
    )
    mv_ts = pos.get("updated_at") or pos.get("as_of") or quote_ts
    cash_ts = holdings_ts
    # advisory / desk
    advisory_ts = (
        decision.get("advisory_as_of")
        or decision.get("verdict_as_of")
        or (decision.get("item") or {}).get("as_of")
        or extra.get("advisory_as_of")
    )
    analyst_ts = decision.get("analyst_as_of") or extra.get("analyst_as_of")
    thesis_ts = decision.get("thesis_as_of") or extra.get("thesis_as_of")
    hermes_ts = decision.get("hermes_as_of") or extra.get("hermes_as_of")
    sector_ts = decision.get("sector_as_of") or extra.get("sector_as_of")
    risk_ts = decision.get("risk_as_of") or extra.get("risk_as_of") or holdings_ts
    tax_ts = decision.get("tax_as_of") or pos.get("last_reconciled_at") or extra.get("tax_as_of")
    decision_ts = (
        decision.get("revalidated_at")
        or decision.get("generated_at")
        or decision.get("computed_at")
        or extra.get("plan_computed_at")
    )
    return {
        "holdings": holdings_ts,
        "quote": quote_ts,
        "market_value": mv_ts,
        "cash": cash_ts,
        "advisory": advisory_ts,
        "analyst": analyst_ts,
        "thesis": thesis_ts,
        "hermes": hermes_ts,
        "sector": sector_ts,
        "risk": risk_ts,
        "tax": tax_ts,
        "decision": decision_ts,
        "sources": {
            "holdings": "holdings.json",
            "quote": pos.get("price_source") or "holdings_quote",
            "market_value": "holdings.market_value",
            "cash": "holdings.cash",
            "advisory": "opportunity_queue/directive",
            "analyst": "analyst_consensus",
            "thesis": "cio_thesis",
            "hermes": "hermes_research",
            "sector": "sector_opportunity",
            "risk": "risk_posture/concentration",
            "tax": "tax_lots/cost_basis",
            "decision": "capital_plan/decision",
        },
    }


def evaluate_decision_actionability(
    decision: dict[str, Any],
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    position_row: Optional[dict[str, Any]] = None,
    financial_truth: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    min_evidence_sources: int = MIN_EVIDENCE_SOURCES_ACT_NOW,
) -> dict[str, Any]:
    """Return action_label + freshness board for one decision."""
    now = now or datetime.now(timezone.utc)
    session = _session_context(now)
    d = decision or {}
    symbol = str(d.get("symbol") or "").upper()
    stance = str(d.get("stance_code") or d.get("cio_stance") or d.get("stance") or "HOLD").upper()
    if stance in ("TRIM", "EXIT", "ADD", "RE_ENTER", "HOLD", "REVIEW"):
        pass
    else:
        # professional labels
        su = stance.upper()
        if "TRIM" in su:
            stance = "TRIM"
        elif "EXIT" in su:
            stance = "EXIT"
        elif "ENTER" in su or "ADD" in su:
            stance = "ADD"
        else:
            stance = "HOLD"

    delta = _fnum(d.get("recommended_delta_usd") if d.get("recommended_delta_usd") is not None else d.get("delta_usd"))
    why = str(d.get("why_now") or "")
    risk = str(d.get("risk") or "")

    ft = financial_truth or {}
    suppress = set(ft.get("suppress_act_now_symbols") or ft.get("conflicted_symbols") or [])
    ft_quality = str(
        d.get("financial_truth_quality")
        or ft.get("overall_quality")
        or STATE_VERIFIED_AS_OF
    )
    ft_ok_for_act = (
        symbol not in suppress
        and ft_quality not in (STATE_CONFLICTED, STATE_DATA_UNAVAILABLE)
        and not d.get("act_now_suppressed")
    )

    stamps = collect_evidence_timestamps(
        decision=d,
        holdings_doc=holdings_doc,
        position_row=position_row,
        financial_truth=ft,
        extra=extra,
    )
    src = stamps.get("sources") or {}

    # Evidence classes
    board = [
        _freshness_record(
            name="holdings", ts=stamps["holdings"], max_age_sec=HOLDINGS_FRESH_SEC,
            now=now, required_for_act_now=True, source=src.get("holdings", ""),
            present=bool(holdings_doc or stamps["holdings"]),
            session=session,
        ),
        _freshness_record(
            name="quote", ts=stamps["quote"], max_age_sec=QUOTE_FRESH_SEC,
            now=now, required_for_act_now=True, source=str(src.get("quote") or ""),
            present=bool(stamps["quote"] or position_row),
            after_hours_ok=True, session=session,
        ),
        _freshness_record(
            name="market_value", ts=stamps["market_value"], max_age_sec=QUOTE_FRESH_SEC,
            now=now, required_for_act_now=True, source=str(src.get("market_value") or ""),
            present=bool(stamps["market_value"] or d.get("current_value_usd") is not None),
            after_hours_ok=True, session=session,
        ),
        _freshness_record(
            name="cash", ts=stamps["cash"], max_age_sec=CASH_FRESH_SEC,
            now=now, required_for_act_now=True, source=str(src.get("cash") or ""),
            present=bool(stamps["cash"] or holdings_doc),
            session=session,
        ),
        _freshness_record(
            name="risk", ts=stamps["risk"], max_age_sec=RISK_FRESH_SEC,
            now=now, required_for_act_now=("concentration" in risk.lower()),
            source=str(src.get("risk") or ""),
            present=bool(risk) or bool(stamps["risk"]),
            session=session,
        ),
        _freshness_record(
            name="advisory", ts=stamps["advisory"], max_age_sec=ADVISORY_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("advisory") or ""),
            present=bool(stamps["advisory"]) or (
                bool(why) and _NEUTRAL_WHY not in why.lower()
            ),
            session=session,
        ),
        _freshness_record(
            name="analyst", ts=stamps["analyst"], max_age_sec=ANALYST_MAX_AGE_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("analyst") or ""),
            present=bool(stamps["analyst"]),
            session=session,
        ),
        _freshness_record(
            name="thesis", ts=stamps["thesis"], max_age_sec=THESIS_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("thesis") or ""),
            present=bool(stamps["thesis"]),
            session=session,
        ),
        _freshness_record(
            name="hermes", ts=stamps["hermes"], max_age_sec=HERMES_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("hermes") or ""),
            present=bool(stamps["hermes"]),
            session=session,
        ),
        _freshness_record(
            name="sector", ts=stamps["sector"], max_age_sec=SECTOR_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("sector") or ""),
            present=bool(stamps["sector"]),
            session=session,
        ),
        _freshness_record(
            name="tax", ts=stamps["tax"], max_age_sec=HOLDINGS_FRESH_SEC,
            now=now, required_for_act_now=False,
            source=str(src.get("tax") or ""),
            present=bool(stamps["tax"]),
            session=session,
        ),
        _freshness_record(
            name="decision", ts=stamps["decision"], max_age_sec=DECISION_REVALIDATE_SEC,
            now=now, required_for_act_now=True,
            source=str(src.get("decision") or ""),
            present=True,  # evaluated now counts if undated → fail undated path
            session=session,
        ),
    ]
    # If decision undated, treat as freshly generated at `now` (this evaluation)
    for rec in board:
        if rec["name"] == "decision" and rec.get("detail") == "undated":
            rec["pass"] = True
            rec["quality"] = STATE_VERIFIED_CURRENT
            rec["age_seconds"] = 0.0
            rec["source_as_of"] = now.isoformat()
            rec["detail"] = "evaluated_now"

    by_name = {r["name"]: r for r in board}

    # Evidence source count: present classes with pass or dated advisory/research
    evidence_sources = [
        r for r in board
        if r["present"] and r["name"] not in ("decision",)
        and r.get("detail") not in ("missing",)
    ]
    # Count only those with some signal
    source_count = 0
    if by_name["holdings"]["present"]:
        source_count += 1
    if by_name["quote"]["present"] or by_name["market_value"]["present"]:
        source_count += 1
    if by_name["advisory"]["present"] and _NEUTRAL_WHY not in why.lower():
        source_count += 1
    if by_name["risk"]["present"] and "concentration" in risk.lower():
        source_count += 1
    if by_name["thesis"]["present"]:
        source_count += 1
    if by_name["hermes"]["present"]:
        source_count += 1
    if by_name["sector"]["present"]:
        source_count += 1
    if by_name["analyst"]["present"]:
        source_count += 1

    required = [r for r in board if r["required_for_act_now"]]
    required_pass = all(r["pass"] for r in required)

    # Material stance?
    is_action_stance = stance in ("TRIM", "EXIT", "ADD", "RE_ENTER")
    has_delta = abs(delta) >= 0.01
    thin_hold = (not is_action_stance) or (
        abs(delta) < 0.01 and _NEUTRAL_WHY in why.lower()
    )

    reasons: list[str] = []
    label = LABEL_WATCH

    # 1) Financial truth conflict
    if not ft_ok_for_act or ft_quality == STATE_CONFLICTED or symbol in suppress:
        label = LABEL_DATA_CONFLICT
        reasons.append("financial_truth_conflict_or_suppressed")
    # 2) Required freshness failures
    elif not required_pass:
        failed = [r["name"] for r in required if not r["pass"]]
        if any(by_name[n]["quality"] == STATE_STALE or by_name[n]["detail"] == "stale" for n in failed if n in by_name):
            label = LABEL_STALE_REFRESH
            reasons.append("required_evidence_stale:" + ",".join(failed))
        elif any(by_name[n]["detail"] in ("undated", "missing") for n in failed if n in by_name):
            label = LABEL_REVALIDATE
            reasons.append("required_evidence_undated_or_missing:" + ",".join(failed))
        else:
            label = LABEL_STALE_REFRESH
            reasons.append("required_freshness_fail:" + ",".join(failed))
    # 3) Thin / non-material
    elif thin_hold or not is_action_stance:
        label = LABEL_WATCH
        reasons.append("non_actionable_stance_or_thin_signal")
    # 4) Insufficient evidence sources
    elif source_count < min_evidence_sources:
        label = LABEL_REVIEW
        reasons.append(f"insufficient_evidence_sources:{source_count}<{min_evidence_sources}")
    # 5) Action stance + delta but needs operator review when only single desk label
    elif is_action_stance and has_delta and source_count >= min_evidence_sources and required_pass and ft_ok_for_act:
        # ACT NOW only if financial truth ok AND not overall STALE book
        if ft_quality == STATE_STALE:
            label = LABEL_STALE_REFRESH
            reasons.append("financial_truth_book_stale")
        else:
            label = LABEL_ACT_NOW
            reasons.append("fresh_material_actionable")
    else:
        label = LABEL_REVIEW
        reasons.append("default_review")

    act_now = label == LABEL_ACT_NOW
    return {
        "version": FRESHNESS_MATERIALITY_VERSION,
        "symbol": symbol,
        "stance": stance,
        "recommended_delta_usd": delta,
        "action_label": label,
        "act_now": act_now,
        "actionable": act_now,  # strict: only ACT_NOW is fully actionable
        "operator_priority": {
            LABEL_ACT_NOW: 0,
            LABEL_DATA_CONFLICT: 1,
            LABEL_STALE_REFRESH: 2,
            LABEL_REVALIDATE: 3,
            LABEL_REVIEW: 4,
            LABEL_WATCH: 5,
        }.get(label, 9),
        "reasons": reasons,
        "evidence_source_count": source_count,
        "min_evidence_sources": min_evidence_sources,
        "financial_truth_quality": ft_quality,
        "financial_truth_ok_for_act_now": ft_ok_for_act,
        "session": session,
        "freshness_board": board,
        "authority": "READ_ONLY_ADVISORY",
    }


def apply_to_decisions(
    decisions: list[dict[str, Any]],
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    financial_truth: Optional[dict[str, Any]] = None,
    extra: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Annotate each decision; return (decisions, summary)."""
    now = now or datetime.now(timezone.utc)
    # Index holdings rows by symbol (first match)
    by_sym: dict[str, dict[str, Any]] = {}
    for r in (holdings_doc or {}).get("holdings") or []:
        if not isinstance(r, dict) or r.get("is_cash"):
            continue
        sym = str(r.get("symbol") or "").upper()
        if sym and sym not in by_sym:
            by_sym[sym] = r

    out: list[dict[str, Any]] = []
    counts: dict[str, int] = {k: 0 for k in ACTION_LABELS}
    act_now_ids: list[str] = []

    for d in decisions or []:
        if not isinstance(d, dict):
            continue
        dd = dict(d)
        sym = str(dd.get("symbol") or "").upper()
        ev = evaluate_decision_actionability(
            dd,
            holdings_doc=holdings_doc,
            position_row=by_sym.get(sym),
            financial_truth=financial_truth,
            extra=extra,
            now=now,
        )
        dd["action_label"] = ev["action_label"]
        dd["act_now"] = ev["act_now"]
        dd["actionable"] = ev["actionable"]
        dd["freshness"] = {
            "version": ev["version"],
            "reasons": ev["reasons"],
            "evidence_source_count": ev["evidence_source_count"],
            "session": ev["session"],
            "board": ev["freshness_board"],
            "financial_truth_quality": ev["financial_truth_quality"],
        }
        # Human prose for operator surfaces
        dd["action_label_display"] = {
            LABEL_ACT_NOW: "ACT NOW",
            LABEL_REVIEW: "REVIEW",
            LABEL_WATCH: "WATCH",
            LABEL_REVALIDATE: "REVALIDATE",
            LABEL_DATA_CONFLICT: "DATA CONFLICT",
            LABEL_STALE_REFRESH: "STALE — REFRESH REQUIRED",
        }.get(ev["action_label"], ev["action_label"])
        counts[ev["action_label"]] = counts.get(ev["action_label"], 0) + 1
        if ev["act_now"]:
            did = dd.get("decision_id") or sym
            act_now_ids.append(str(did))
        out.append(dd)

    summary = {
        "version": FRESHNESS_MATERIALITY_VERSION,
        "evaluated_at": now.isoformat(),
        "counts": counts,
        "act_now_count": counts.get(LABEL_ACT_NOW, 0),
        "act_now_decision_ids": act_now_ids,
        "authority": "READ_ONLY_ADVISORY",
    }
    raw = json.dumps({"counts": counts, "act_now": act_now_ids}, sort_keys=True)
    summary["gate_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    return out, summary


def attach_to_capital_plan(
    plan: dict[str, Any],
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Apply freshness/materiality after financial truth attachment."""
    out = dict(plan)
    ft = out.get("financial_truth_gate") or {}
    extra = {"plan_computed_at": out.get("computed_at") or out.get("as_of")}
    decisions, summary = apply_to_decisions(
        out.get("position_decisions") or [],
        holdings_doc=holdings_doc,
        financial_truth=ft,
        extra=extra,
        now=now,
    )
    out["position_decisions"] = decisions
    out["freshness_materiality_gate"] = summary
    return out
