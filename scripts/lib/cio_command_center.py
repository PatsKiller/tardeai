"""cio_command_center.py — Phase 8 office-home composition (pure, advisory-only).

Turns the CIO surfaces built in Phases 5–7 (capital plan, sector synthesis,
opportunity queue, institutional report, thesis) into one "office home" payload
for `/v3/cio`, so the operator stops browsing pages to discover decisions.

Six sections, decision-first:

  CIO NOW · CAPITAL PLAN · PORTFOLIO POSTURE · OPPORTUNITIES · REPORT · EVIDENCE

Everything here is pure and deterministic: live readers are injected as dicts by
the API wrapper, so the composition (and its dry tests) never touch the DB,
broker, or an LLM. Labels are plain English; internal snake_case codes are kept
only in the `evidence` section (which is explicitly the "internal codes" space),
never in a primary view.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

OFFICE_HOME_VERSION = "office_home_1.0.0"

# Human labels for stance / posture / readiness codes surfaced in primary views.
STANCE_LABELS: dict[str, str] = {
    "HOLD": "Hold",
    "TRIM": "Trim",
    "ADD": "Add",
    "BUY": "Buy",
    "SELL": "Sell",
    "RE_ENTER": "Re-enter",
    "EXIT": "Exit",
    "ROTATE": "Rotate",
    "DEFENSIVE": "Defensive",
    "OFFENSIVE": "Offensive",
    "neutral_hold": "Neutral · hold",
    "defensive_observe": "Defensive · observe",
    "defensive_trim": "Defensive · trim",
    "offensive_add": "Offensive · add",
}

READINESS_LABELS: dict[str, str] = {
    "READY": "ready",
    "NEEDS_RESEARCH": "needs research",
    "TOO_EXTENDED": "too extended",
    "BLOCKED": "blocked",
}

CASH_POSTURE_LABELS: dict[str, str] = {
    "ABOVE_BAND": "above policy band",
    "IN_BAND": "in policy band",
    "BELOW_BAND": "below policy band",
}


def _now_iso(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def _human_stance(s: Any) -> str:
    return STANCE_LABELS.get(_str(s), (_str(s).replace("_", " ").strip() or "—"))


# Advisory signals embedded in the opportunity queue's directive labels (and in
# capital-plan "why_now" strings). When the CIO's formal stance is "Hold" but a
# desk flagged a concrete signal, the decision card shows that signal instead.
_ACTION_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("RE_ENTER", "Re-enter"), ("RE-ENTER", "Re-enter"), ("REENTER", "Re-enter"),
    ("TRIM", "Trim"), ("ADD", "Add"), ("BUY", "Buy"), ("SELL", "Sell"),
    ("EXIT", "Exit"), ("SHORT", "Short"), ("DEPLOY", "Deploy"), ("INCOME", "Income"),
)


def _action_hint(why_now: Any, stance: Any) -> str:
    """Derive the most actionable verb from an advisory signal string.

    Prefers a desk signal embedded in `why_now` (e.g. "Advisory TRIM — SCHD")
    over the formal CIO stance, so a "Hold" stance paired with a "Trim" signal
    reads as "Trim" rather than the contradictory "Hold".
    """
    try:
        from scripts.lib.cio_decision_semantics import (
            resolve_display_stance, professional_stance,
        )
        return professional_stance(resolve_display_stance(stance, why_now))
    except Exception:
        pass
    text = _str(why_now).upper()
    for kw, label in _ACTION_KEYWORDS:
        if kw in text:
            return label
    return _human_stance(stance)

# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — CIO NOW
# ─────────────────────────────────────────────────────────────────────────────

_NEUTRAL_WHY = "no new desk signal; hold"


def build_cio_now(
    *,
    position_decisions: Optional[list[dict[str, Any]]] = None,
    actions: Optional[list[dict[str, Any]]] = None,
    plans: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """Decision cards from position decisions + open actions, sorted by urgency.

    A decision surfaces when it carries a real signal: a non-zero recommended
    delta, a non-neutral "why now", or a concentration/risk breach. Pure "hold
    because nothing changed" rows are omitted (they are not decisions).
    """
    cards: list[dict[str, Any]] = []

    for d in position_decisions or []:
        why = _str(d.get("why_now"))
        risk = _str(d.get("risk"))
        delta = _num(d.get("recommended_delta_usd")) or 0.0
        has_signal = bool(why) and _NEUTRAL_WHY not in why
        has_breach = "concentration >" in risk.lower() or "breach" in risk.lower()
        if not (delta or has_signal or has_breach):
            continue
        urgency = "high" if has_breach else ("medium" if delta else "low")
        cards.append({
            "kind": "position",
            "symbol": d.get("symbol"),
            "account": d.get("account"),
            "stance": _action_hint(why, d.get("cio_stance")),
            "delta_usd": delta,
            "value_usd": _num(d.get("current_value_usd")),
            "weight_pct": _num(d.get("current_weight_pct")),
            "why_now": why,
            "risk": risk,
            "urgency": urgency,
            "next_review": d.get("next_review"),
            "tax_note": d.get("tax_account_constraint"),
            "counter_thesis": d.get("counter_thesis"),
        })

    for a in actions or []:
        cards.append({
            "kind": "action",
            "symbol": None,
            "stance": "Action",
            "delta_usd": 0.0,
            "value_usd": None,
            "weight_pct": None,
            "why_now": _str(a.get("why_now") or a.get("title") or a.get("recommendation")),
            "risk": None,
            "urgency": "high" if a.get("notification_priority") in ("Critical", "High") else "medium",
            "next_review": None,
            "action_id": a.get("cio_action_id"),
            "domain": a.get("domain"),
        })

    _URG = {"high": 0, "medium": 1, "low": 2}
    cards.sort(key=lambda c: (_URG.get(c["urgency"], 3), -abs(c["delta_usd"] or 0.0)))

    return {
        "decisions": cards[:5],
        "decision_count": len(cards),
        "open_actions_count": len(actions or []),
        "open_plans_count": len(plans or []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Capital Plan
# ─────────────────────────────────────────────────────────────────────────────

def _money_rows(rows: Optional[dict[str, Any]], keys: tuple[str, ...],
                labels: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k, lbl in zip(keys, labels):
        v = _num((rows or {}).get(k))
        if v is not None:
            out.append({"label": lbl, "usd": v})
    return out


def build_capital_plan(plan: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    p = plan or {}
    band = p.get("cash_policy_band") or {}
    sources = _money_rows(
        p.get("capital_sources"),
        ("trims_usd", "exits_usd", "maturities_usd", "total_raise_usd"),
        ("Trims", "Exits", "Maturities", "Total raise"),
    )
    uses = _money_rows(
        p.get("capital_uses"),
        ("adds_usd", "new_positions_usd", "reentry_usd", "sector_rotation_usd",
         "reserve", "total_deploy_request_usd"),
        ("Add to holdings", "New positions", "Re-entry", "Sector rotation",
         "Reserve", "Total deploy request"),
    )
    return {
        "cash_total_usd": _num(p.get("cash_total_usd")),
        "cash_reserved_usd": _num(p.get("cash_reserved_usd")),
        "cash_investable_usd": _num(p.get("cash_investable_usd")),
        "cash_band": {
            "min_pct": _num(band.get("min_pct")),
            "max_pct": _num(band.get("max_pct")),
        },
        "recommended_deploy_usd": _num(p.get("net_recommended_deploy_usd")),
        "recommended_raise_usd": _num(p.get("net_recommended_raise_usd")),
        "sources": sources,
        "uses": uses,
        "post_plan_cash_usd": _num(p.get("post_plan_cash_usd")),
        "post_plan_cash_pct": _num(p.get("post_plan_cash_pct")),
        "cash_posture": CASH_POSTURE_LABELS.get(
            _str(p.get("cash_posture_status")), _str(p.get("cash_posture_status") or "—")
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Portfolio Posture
# ─────────────────────────────────────────────────────────────────────────────

def build_posture(
    *,
    capital_plan: Optional[dict[str, Any]] = None,
    sector_opportunities: Optional[dict[str, Any]] = None,
    attribution: Optional[dict[str, Any]] = None,
    thesis: Optional[dict[str, Any]] = None,
    income: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    plan = capital_plan or {}
    attr = attribution or {}
    th = thesis or {}
    inc = income or {}

    # Concentration: top position weight + the concentration fire threshold.
    top = None
    for d in plan.get("position_decisions") or []:
        w = _num(d.get("current_weight_pct"))
        if w is not None and (top is None or w > top["weight_pct"]):
            top = {"symbol": d.get("symbol"), "weight_pct": w}
    fire_pct = None
    for c in plan.get("portfolio_constraints") or []:
        if isinstance(c, dict) and c.get("kind") == "concentration_fire_pct":
            fire_pct = _num(c.get("value"))

    opportunities = (sector_opportunities or {}).get("opportunities") or []
    sector_tilts = []
    for o in opportunities:
        if not isinstance(o, dict):
            continue
        sector_tilts.append({
            "sector": o.get("sector"),
            "state": o.get("state"),
            "exposure_pct": _num(o.get("current_exposure_pct")),
            "target_pct": _num(o.get("target_posture_pct")),
            "recommendation": o.get("recommendation"),
        })

    tax_issues: list[str] = []
    for d in plan.get("position_decisions") or []:
        note = d.get("tax_account_constraint")
        if note and "tax-advantaged" not in _str(note):
            tax_issues.append(f"{d.get('symbol')}: {note}")

    constraints: list[str] = []
    for c in plan.get("portfolio_constraints") or []:
        if isinstance(c, dict) and c.get("kind"):
            constraints.append(f"{c.get('kind')}: {c.get('value')}")

    principles = list(th.get("principles") or [])[:4]

    return {
        "thesis": {
            "stance": _human_stance(th.get("stance")),
            "summary": _str(th.get("summary") or "").strip() or None,
            "principles": principles,
        },
        "concentration": {
            "top_position": top["symbol"] if top else None,
            "top_weight_pct": top["weight_pct"] if top else None,
            "fire_pct": fire_pct,
        },
        "risk_heat": {
            "max_drawdown_pct": _num(attr.get("port_maxdd")),
            "sharpe": _num(attr.get("port_sharpe")),
            "sortino": _num(attr.get("port_sortino")),
        },
        "sector_tilts": sector_tilts[:8],
        "performance": {
            "portfolio_cagr": _num(attr.get("port_cagr")),
            "benchmark_cagr": _num(attr.get("bench_cagr")),
            "alpha_annualized": _num(attr.get("alpha_annualized")),
            "benchmark_label": attr.get("benchmark_label"),
        },
        "income": {
            "total_usd": _num(inc.get("grand_total_income")),
        },
        "tax_issues": tax_issues[:5],
        "constraints": constraints[:6],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Opportunities
# ─────────────────────────────────────────────────────────────────────────────

def build_opportunities(
    *,
    queue: Optional[dict[str, Any]] = None,
    sector_opportunities: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    q = queue or {}
    items = q.get("items") or q.get("top") or []

    watch: list[dict[str, Any]] = []
    reentry: list[dict[str, Any]] = []
    seen_watch: set[str] = set()
    seen_reentry: set[str] = set()
    for it in items:
        if not isinstance(it, dict):
            continue
        symbol = it.get("symbol")
        # The queue carries the human signal in directive_label (e.g.
        # "Advisory TRIM — SCHD"); verdict/state are often null.
        label = _str(it.get("directive_label") or "").upper()
        source = it.get("source")
        signal = _action_hint(it.get("directive_label"), it.get("verdict"))
        rec = {
            "symbol": symbol,
            "source": source,
            "signal": signal,
            "label": it.get("directive_label"),
        }
        if "RE_ENTER" in label or "RE-ENTER" in label or "REENTER" in label:
            if symbol not in seen_reentry:
                reentry.append(rec)
                seen_reentry.add(symbol)
        elif symbol not in seen_watch:
            watch.append(rec)
            seen_watch.add(symbol)

    rotation: list[dict[str, Any]] = []
    research_gaps: list[dict[str, Any]] = []
    for o in (sector_opportunities or {}).get("opportunities") or []:
        if not isinstance(o, dict):
            continue
        rotation.append({
            "sector": o.get("sector"),
            "state": o.get("state"),
            "recommendation": o.get("recommendation"),
        })
        for c in o.get("candidates") or []:
            if not isinstance(c, dict):
                continue
            readiness = _str(c.get("readiness")).upper()
            if readiness == "NEEDS_RESEARCH":
                research_gaps.append({"symbol": c.get("symbol"), "sector": o.get("sector")})

    return {
        "watch": watch[:8],
        "reentry": reentry[:6],
        "rotation": rotation[:8],
        "research_gaps": research_gaps[:8],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — Report
# ─────────────────────────────────────────────────────────────────────────────

def build_report_section(report: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    r = report or {}
    manifest = r.get("manifest") or {}
    checkpoint = r.get("checkpoint") or {}
    coverage = r.get("coverage") or {}
    return {
        "as_of": r.get("as_of"),
        "report_version": r.get("report_version"),
        "source_sha": manifest.get("source_sha"),
        "manifest_hash": manifest.get("manifest_hash"),
        "source_traceability_pct": checkpoint.get("source_traceability_pct"),
        "field_count": coverage.get("field_count"),
        "fields_present": len(checkpoint.get("fields_present") or []),
        "fields_unavailable": checkpoint.get("fields_unavailable") or [],
        "quality_flag_count": len(checkpoint.get("quality_flags") or []),
        "pdf_pages": checkpoint.get("pdf_pages"),
        "render_errors": checkpoint.get("render_errors") or [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — Evidence / Audit
# ─────────────────────────────────────────────────────────────────────────────

def build_evidence(
    *,
    report: Optional[dict[str, Any]] = None,
    source_refs: Optional[list[dict[str, Any]]] = None,
    validator_states: Optional[list[dict[str, Any]]] = None,
    run_ids: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    r = report or {}
    manifest = r.get("manifest") or {}
    internal_codes: list[str] = []
    for fid in (r.get("checkpoint") or {}).get("fields_unavailable") or []:
        internal_codes.append(fid)

    return {
        "as_of": r.get("as_of") or _now_iso(now),
        "report_version": r.get("report_version") or OFFICE_HOME_VERSION,
        "authority": r.get("authority") or "READ_ONLY_ADVISORY",
        "source_sha": manifest.get("source_sha"),
        "source_refs": source_refs or [],
        "validator_states": validator_states or [],
        "run_ids": run_ids or [],
        "internal_codes": internal_codes,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Composition
# ─────────────────────────────────────────────────────────────────────────────

def build_office_home(
    *,
    capital_plan: Optional[dict[str, Any]] = None,
    sector_opportunities: Optional[dict[str, Any]] = None,
    opportunity_queue: Optional[dict[str, Any]] = None,
    report: Optional[dict[str, Any]] = None,
    thesis: Optional[dict[str, Any]] = None,
    attribution: Optional[dict[str, Any]] = None,
    income: Optional[dict[str, Any]] = None,
    actions: Optional[list[dict[str, Any]]] = None,
    plans: Optional[list[dict[str, Any]]] = None,
    source_refs: Optional[list[dict[str, Any]]] = None,
    validator_states: Optional[list[dict[str, Any]]] = None,
    run_ids: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    return {
        "version": OFFICE_HOME_VERSION,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": _now_iso(now),
        "cio_now": build_cio_now(
            position_decisions=(capital_plan or {}).get("position_decisions"),
            actions=actions,
            plans=plans,
        ),
        "capital_plan": build_capital_plan(capital_plan),
        "posture": build_posture(
            capital_plan=capital_plan,
            sector_opportunities=sector_opportunities,
            attribution=attribution,
            thesis=thesis,
            income=income,
        ),
        "opportunities": build_opportunities(
            queue=opportunity_queue,
            sector_opportunities=sector_opportunities,
        ),
        "report": build_report_section(report),
        "evidence": build_evidence(
            report=report,
            source_refs=source_refs,
            validator_states=validator_states,
            run_ids=run_ids,
            now=now,
        ),
    }
