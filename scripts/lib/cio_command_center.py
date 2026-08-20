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

OFFICE_HOME_VERSION = "office_home_1.3.0"  # Phase 6–13: strategy context on home

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


# Phase 4: action labels that mean "investment decision needs operator"
_INVESTMENT_ATTENTION_LABELS = frozenset({
    "ACT_NOW", "REVIEW", "REVALIDATE", "DATA_CONFLICT", "STALE_REFRESH_REQUIRED",
})
_OPEN_PLAN_STATUSES = frozenset({
    "open", "active", "pending", "proposed", "in_progress", "draft",
})


def _investment_needs_attention(d: dict[str, Any]) -> bool:
    """True CIO InvestmentDecision needing operator — not workflow noise."""
    label = _str(d.get("action_label") or "").upper()
    if label in _INVESTMENT_ATTENTION_LABELS:
        return True
    if d.get("act_now") is True:
        return True
    risk = _str(d.get("risk")).lower()
    if "concentration" in risk and (">" in risk or "fire" in risk or "breach" in risk):
        return True
    stance = _str(d.get("stance_code") or d.get("cio_stance") or d.get("stance")).upper()
    delta = abs(_num(d.get("recommended_delta_usd") if d.get("recommended_delta_usd") is not None else d.get("delta_usd")) or 0.0)
    why = _str(d.get("why_now"))
    non_neutral = bool(why) and _NEUTRAL_WHY not in why.lower()
    if stance in ("TRIM", "EXIT", "ADD", "RE_ENTER") and (delta >= 0.01 or non_neutral):
        # A TRIM/EXIT/ADD/RE_ENTER directive with $0 recommended delta is a
        # scenario-only / declined decision (no verified objective). It still
        # needs operator REVIEW, so it must surface rather than vanish.
        return True
    if non_neutral and delta >= 0.01:
        return True
    # Explicit WATCH / thin hold → not investment attention
    if label == "WATCH" or stance in ("HOLD", ""):
        return False
    return False


def _plan_is_open(p: Any) -> bool:
    if not isinstance(p, dict):
        return False
    st = _str(p.get("status") or p.get("state") or "open").lower()
    if st in ("cancelled", "canceled", "closed", "done", "rejected", "accepted", "complete", "completed"):
        return False
    if st in _OPEN_PLAN_STATUSES or not st:
        return True
    return st not in ("unknown",)


def _action_is_open(a: Any) -> bool:
    if not isinstance(a, dict):
        return False
    st = _str(a.get("status") or a.get("state") or "open").lower()
    if st in ("done", "closed", "cancelled", "canceled", "rejected", "complete", "completed"):
        return False
    return True


def _freshness_flag(d: dict[str, Any]) -> str:
    """Normalize a decision's freshness field to an upper-case state string.

    Delegates to the canonical semantics helper so Command Center and Telegram
    share one freshness interpretation.
    """
    from scripts.lib.cio_decision_semantics import freshness_flag
    return freshness_flag(d)


def _canonical_action(d: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """(effective_act_now, blocking_state) via the shared canonical classifier."""
    from scripts.lib.cio_decision_semantics import canonical_act_now
    return canonical_act_now(d)


def _actionability_urgency(d: dict[str, Any]) -> str:
    """Actionability-derived urgency — fail-closed against stale/conflict.

    Priority: DATA_CONFLICT / STALE_REFRESH_REQUIRED / REVALIDATE (and a stale/
    expired freshness flag) override any ACT_NOW signal. Only a fresh decision
    that is explicitly actionable (act_now=True or ACT_NOW label) is "high".
    Risk text such as "concentration > fire" is a fact, never an action.
    """
    act_now, blocking = _canonical_action(d)
    label = _str(d.get("action_label") or "").upper()
    if blocking:
        return "medium"
    if act_now:
        return "high"
    if label == "REVIEW":
        return "medium"
    return "low"


def build_cio_now(
    *,
    position_decisions: Optional[list[dict[str, Any]]] = None,
    actions: Optional[list[dict[str, Any]]] = None,
    plans: Optional[list[dict[str, Any]]] = None,
    portfolio_value: Optional[float] = None,
) -> dict[str, Any]:
    """CIO NOW — at most 5 investment decision cards + disjoint attention KPIs.

    Phase 4 attention model (no double-count across KPI buckets):
      INVESTMENT DECISIONS — true InvestmentDecision objects needing attention
      WORKFLOW ACTIONS     — open action-ledger items only
      OPEN PLANS           — durable plans still open
      MATERIAL TODAY       — deduped unique high-priority items (target 0–5)

    Cards shown are investment decisions only (not workflow actions).
    """
    cards: list[dict[str, Any]] = []
    investment_pool: list[dict[str, Any]] = []

    # Prefer sanitizer so IDs match the institutional report.
    try:
        from scripts.lib.cio_decision_semantics import (
            sanitize_decisions_now, operator_action_affordances,
        )
        sanitized = sanitize_decisions_now(
            position_decisions or [],
            portfolio_value=float(portfolio_value or 0.0),
            limit=24,
        )
        # Preserve Phase 3/5 annotations from capital-plan rows by symbol
        by_sym = {
            _str(d.get("symbol")).upper(): d
            for d in (position_decisions or [])
            if isinstance(d, dict) and d.get("symbol")
        }
        for d in sanitized:
            raw = by_sym.get(_str(d.get("symbol")).upper()) or {}
            # merge annotation fields from plan row
            for k in (
                "action_label", "action_label_display", "act_now", "actionable",
                "freshness", "sizing", "sizing_method", "sizing_objective",
                "sizing_why_not_min", "sizing_why_not_max",
                "trim_to_clear_fire_usd", "trim_to_policy_usd",
                "fallback_candidate_only", "financial_truth_quality",
                "candidates", "sizing_quality", "selected_candidate",
                "selection_rationale", "tranches",
            ):
                if k in raw and k not in d:
                    d[k] = raw[k]
                elif k in raw and not d.get(k):
                    d[k] = raw[k]
            risk = _str(d.get("risk") or raw.get("risk"))
            delta = _num(d.get("recommended_delta_usd")) or 0.0
            urgency = _actionability_urgency(d)
            value_usd = _num(d.get("current_value_usd"))
            weight_pct = _num(d.get("current_weight_pct"))
            card = {
                "kind": "position",
                "decision_id": d.get("decision_id"),
                "symbol": d.get("symbol"),
                "account": (d.get("accounts") or [None])[0] if d.get("accounts") else d.get("account"),
                "action": d.get("action") or d.get("stance"),
                "stance": d.get("stance"),
                "stance_code": d.get("stance_code"),
                # Short card keys (UI) + full parity aliases (Phase 7)
                "delta_usd": delta,
                "value_usd": value_usd,
                "weight_pct": weight_pct,
                "recommended_delta_usd": delta,
                "current_value_usd": value_usd,
                "current_weight_pct": weight_pct,
                "target_weight_pct": _num(d.get("target_weight_pct")),
                "why_now": d.get("why_now"),
                "counter_thesis": d.get("counter_thesis"),
                "what_changes_call": d.get("what_changes_call"),
                "risk": risk,
                "urgency": urgency,
                "next_review": d.get("next_review"),
                "tax_note": d.get("tax_account_constraint"),
                "operator_actions": d.get("operator_actions") or operator_action_affordances(),
                "action_label": d.get("action_label") or raw.get("action_label"),
                "action_label_display": d.get("action_label_display") or raw.get("action_label_display"),
                "act_now": d.get("act_now") if d.get("act_now") is not None else raw.get("act_now"),
                "freshness": d.get("freshness") if d.get("freshness") is not None else raw.get("freshness"),
                "sizing_objective": d.get("sizing_objective") or raw.get("sizing_objective"),
                "sizing_method": d.get("sizing_method") or raw.get("sizing_method"),
                "trim_to_clear_fire_usd": d.get("trim_to_clear_fire_usd") or raw.get("trim_to_clear_fire_usd"),
                "trim_to_policy_usd": d.get("trim_to_policy_usd") or raw.get("trim_to_policy_usd"),
                "scenario_trim_usd": d.get("scenario_trim_usd") if d.get("scenario_trim_usd") is not None else raw.get("scenario_trim_usd"),
                "target_status": d.get("target_status") if d.get("target_status") is not None else raw.get("target_status"),
                "decision_input_digest": d.get("decision_input_digest") or raw.get("decision_input_digest") or "",
                "decision_evidence_digest": d.get("decision_evidence_digest") or raw.get("decision_evidence_digest") or "",
            }
            investment_pool.append(card)
    except Exception:
        for d in position_decisions or []:
            if not isinstance(d, dict):
                continue
            why = _str(d.get("why_now"))
            risk = _str(d.get("risk"))
            delta = _num(d.get("recommended_delta_usd")) or 0.0
            has_signal = bool(why) and _NEUTRAL_WHY not in why
            has_breach = "concentration" in risk.lower() or "breach" in risk.lower() or "fire" in risk.lower()
            if not (delta or has_signal or has_breach or d.get("act_now") or d.get("action_label")):
                continue
            # Fail-closed: the same freshness-aware classifier as the normal path.
            urgency = _actionability_urgency(d)
            stance = _action_hint(why, d.get("cio_stance") or d.get("stance_code"))
            value_usd = _num(d.get("current_value_usd"))
            weight_pct = _num(d.get("current_weight_pct"))
            investment_pool.append({
                "kind": "position",
                "decision_id": d.get("decision_id") or f"dec_fallback_{d.get('symbol')}",
                "symbol": d.get("symbol"),
                "account": d.get("account"),
                "action": stance,
                "stance": stance,
                "stance_code": d.get("stance_code") or d.get("cio_stance"),
                "delta_usd": delta,
                "value_usd": value_usd,
                "weight_pct": weight_pct,
                "recommended_delta_usd": delta,
                "current_value_usd": value_usd,
                "current_weight_pct": weight_pct,
                "target_weight_pct": _num((d.get("target_range_pct") or {}).get("max"))
                if isinstance(d.get("target_range_pct"), dict) else _num(d.get("target_weight_pct")),
                "why_now": why,
                "counter_thesis": d.get("counter_thesis"),
                "what_changes_call": d.get("what_changes_call"),
                "risk": risk,
                "urgency": urgency,
                "next_review": d.get("next_review"),
                "tax_note": d.get("tax_account_constraint"),
                "operator_actions": [
                    {"code": "ACK", "label": "Acknowledge"},
                    {"code": "DEFER", "label": "Defer"},
                    {"code": "DONE", "label": "Mark done"},
                    {"code": "REJECT", "label": "Reject"},
                    {"code": "RATE", "label": "Rate"},
                ],
                "action_label": d.get("action_label"),
                "action_label_display": d.get("action_label_display"),
                "act_now": d.get("act_now"),
                "freshness": d.get("freshness"),
                "sizing_objective": d.get("sizing_objective"),
                "sizing_method": d.get("sizing_method"),
                "scenario_trim_usd": d.get("scenario_trim_usd"),
                "target_status": d.get("target_status"),
                "decision_input_digest": d.get("decision_input_digest") or "",
                "decision_evidence_digest": d.get("decision_evidence_digest") or "",
            })

    # Phase 4: investment decisions needing attention (disjoint from actions/plans)
    needing = [c for c in investment_pool if _investment_needs_attention(c)]
    # Sort from the derived, freshness-aware current action — never raw act_now.
    def _sort_key(c: dict[str, Any]) -> tuple:
        act_now, blocking = _canonical_action(c)
        # ACT-NOW tier only when explicitly actionable AND unblocked.
        act = 0 if act_now else 1
        urg = {"high": 0, "medium": 1, "low": 2}.get(c.get("urgency") or "low", 3)
        return (act, urg, -abs(c.get("delta_usd") or 0.0))

    needing.sort(key=_sort_key)
    cards = needing[:5]  # CIO NOW shows at most five investment decisions

    open_actions = [a for a in (actions or []) if _action_is_open(a)]
    # plans may be list or dict
    plan_list: list[Any] = []
    if isinstance(plans, dict):
        plan_list = list(plans.values()) if not isinstance(plans.get("plans"), (list, dict)) else (
            plans.get("plans") if isinstance(plans.get("plans"), list)
            else list((plans.get("plans") or {}).values())
        )
    elif isinstance(plans, list):
        plan_list = plans
    open_plans = [p for p in plan_list if _plan_is_open(p)]

    # Material Today: deduped unique high-priority items. Uses the derived,
    # freshness-aware current action; a stale act_now=True record may remain
    # material (it needs revalidation) but never occupies the ACT-NOW tier.
    material_keys: list[str] = []
    for c in needing:
        act_now, blocking = _canonical_action(c)
        if act_now or blocking or c.get("urgency") == "high":
            key = _str(c.get("decision_id") or c.get("symbol"))
            if key and key not in material_keys:
                material_keys.append(key)
    for a in open_actions:
        if a.get("notification_priority") in ("Critical", "High") or _str(a.get("urgency")).lower() == "high":
            aid = _str(a.get("cio_action_id") or a.get("action_id") or a.get("symbol"))
            key = f"act:{aid}"
            if key not in material_keys and not any(
                _str(c.get("symbol")) == _str(a.get("symbol")) for c in needing if a.get("symbol")
            ):
                material_keys.append(key)

    material_today = len(material_keys)
    # Operator UX target: Material Today normally 0–5 (we still report true count)
    investment_decisions_count = len(needing)
    workflow_actions_count = len(open_actions)
    open_plans_count = len(open_plans)

    return {
        "decisions": cards,
        "decision_ids": [c.get("decision_id") for c in cards if c.get("decision_id")],
        # Phase 4 primary attention KPIs (disjoint semantics)
        "attention": {
            "investment_decisions": investment_decisions_count,
            "workflow_actions": workflow_actions_count,
            "open_plans": open_plans_count,
            "material_today": material_today,
            "material_today_ids": material_keys[:12],
            "labels": {
                "investment_decisions": "Investment decisions",
                "workflow_actions": "Workflow actions",
                "open_plans": "Open plans",
                "material_today": "Material today",
            },
            "note": (
                "KPIs are disjoint: investment decisions are InvestmentDecision objects; "
                "workflow actions are action-ledger items; open plans are durable plans. "
                "Material today is a deduped priority set — not the sum of the three."
            ),
        },
        # Backward-compatible aliases (investment attention, not total card mix)
        "decision_count": investment_decisions_count,
        "open_actions_count": workflow_actions_count,
        "open_plans_count": open_plans_count,
        "material_today_count": material_today,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Capital Plan
# ─────────────────────────────────────────────────────────────────────────────

def _money_rows(rows: Optional[dict[str, Any]], keys: tuple[str, ...],
                labels: tuple[str, ...]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    custom = (rows or {}).get("component_labels") or {}
    for k, lbl in zip(keys, labels):
        v = _num((rows or {}).get(k))
        if v is not None:
            out.append({"label": str(custom.get(k) or lbl), "usd": v, "key": k})
    return out


def build_capital_plan(plan: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Capital plan surface for /v3/cio — Phase 2 semantics, shared digest with report.

    Shows settled cash, reserve, earmark (label on cash — not a raise), free
    investable, prospective sources, recommended deploy, post-plan cash, accounts.
    """
    p = plan or {}
    band = p.get("cash_policy_band") or {}
    src = p.get("capital_sources") or {}
    uses_raw = p.get("capital_uses") or {}
    earmark = _num(
        p.get("cash_earmarked_redeploy_usd")
        or src.get("earmarked_redeploy_usd")
        or src.get("maturities_usd")
    )
    prospective = _num(
        src.get("total_prospective_raise_usd")
        if src.get("total_prospective_raise_usd") is not None
        else p.get("net_recommended_raise_usd")
        if p.get("net_recommended_raise_usd") is not None
        else src.get("total_raise_usd")
    )
    # Sources: never present earmarked cash as "new raise"
    sources = _money_rows(
        {
            **src,
            "earmarked_redeploy_usd": earmark,
            "total_prospective_raise_usd": prospective,
        },
        ("trims_usd", "exits_usd", "earmarked_redeploy_usd", "total_prospective_raise_usd"),
        ("Trims (prospective)", "Exits (prospective)",
         "Earmarked redeploy (already in cash)", "Prospective raise"),
    )
    # Backward-compat: if only total_raise_usd present without prospective field
    if not any(s["label"] == "Prospective raise" for s in sources) and _num(src.get("total_raise_usd")) is not None:
        sources.append({"label": "Prospective raise", "usd": _num(src.get("total_raise_usd"))})
    uses = _money_rows(
        uses_raw,
        ("adds_usd", "new_positions_usd", "reentry_usd", "sector_rotation_usd",
         "reserve", "fundable_deploy_request_usd", "total_deploy_request_usd"),
        ("Add to holdings", "New positions", "Re-entry",
         "Sector rotation (notional gap)",
         "Reserve (held, not deployed)",
         "Fundable deploy request",
         "Total deploy request (fundable + notional sector gaps)"),
    )
    try:
        from scripts.lib.cio_decision_semantics import capital_plan_surface_digest
        digest = capital_plan_surface_digest(p)
    except Exception:
        digest = p.get("digest")
    account_cash = p.get("account_cash") or (p.get("cash_ledger") or {}).get("account_cash") or []
    free_unearmarked = _num(p.get("cash_free_unearmarked_usd"))
    if free_unearmarked is None and _num(p.get("cash_total_usd")) is not None:
        free_unearmarked = max(0.0, float(p.get("cash_total_usd") or 0) - float(earmark or 0))
    deploy_funding = p.get("deploy_funding") or {}
    if not deploy_funding:
        investable = _num(p.get("cash_investable_usd"))
        recommended = _num(p.get("net_recommended_deploy_usd"))
        if investable is not None and recommended is not None:
            gap = round(max(0.0, recommended - investable), 2)
            deploy_funding = {
                "recommended_deploy_usd": recommended,
                "investable_cash_usd": investable,
                "prospective_raise_usd": prospective,
                "deployable_usd": _num(p.get("deployable_usd")),
                "deploy_exceeds_investable_cash": recommended > investable + 0.01,
                "gap_vs_investable_cash_usd": gap,
                "note": (
                    f"Recommended deploy exceeds investable cash by ${gap:,.0f}."
                    if gap > 0.01
                    else "Recommended deploy is within investable cash."
                ),
            }
    return {
        "cash_total_usd": _num(p.get("cash_total_usd")),
        "cash_reserved_usd": _num(p.get("cash_reserved_usd")),
        "cash_earmarked_redeploy_usd": earmark,
        "cash_free_unearmarked_usd": free_unearmarked,
        "cash_investable_usd": _num(p.get("cash_investable_usd")),
        "deployable_usd": _num(p.get("deployable_usd")),
        "cash_band": {
            "min_pct": _num(band.get("min_pct")),
            "max_pct": _num(band.get("max_pct")),
        },
        "recommended_deploy_usd": _num(p.get("net_recommended_deploy_usd")),
        "recommended_raise_usd": prospective,  # prospective only
        "sources": sources,
        "uses": uses,
        "deploy_funding": deploy_funding,
        "deploy_request_notes": uses_raw.get("deploy_request_notes") or [],
        "post_plan_cash_usd": _num(p.get("post_plan_cash_usd")),
        "post_plan_cash_pct": _num(p.get("post_plan_cash_pct")),
        "account_cash": account_cash,
        "plan_version": p.get("plan_version"),
        "plan_digest": digest,
        "double_count_guard": src.get("double_count_guard") or "earmarked_redeploy_excluded_from_raise",
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
        # Professional prose only in primary posture (raw codes stay in evidence)
        rec = o.get("recommendation")
        state = o.get("state")
        try:
            from scripts.lib.cio_decision_semantics import professional_label, is_pseudo_sector
            if is_pseudo_sector(o.get("sector")):
                continue
            rec = professional_label(rec) if rec else rec
            state = professional_label(state) if state else state
        except Exception:
            pass
        sector_tilts.append({
            "sector": o.get("sector"),
            "state": state,
            "exposure_pct": _num(o.get("current_exposure_pct")),
            "target_pct": _num(o.get("target_posture_pct")),
            "target_source": o.get("target_source"),
            "target_label": o.get("target_label"),
            "target_is_placeholder": bool(o.get("target_is_placeholder")),
            "recommendation": rec,
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

    target_honesty = (sector_opportunities or {}).get("sector_target_honesty") or {}
    bench_label = attr.get("benchmark_label")
    bench_source = attr.get("benchmark_source") or (
        "portfolio_performance_attribution blended policy "
        "(55% SPY / 20% ITA / 25% AGG) — ITA is the 20% defense sleeve of the blend, "
        "not a standalone portfolio target"
        if bench_label
        else None
    )

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
        "sector_target_honesty": target_honesty,
        "performance": {
            "portfolio_cagr": _num(attr.get("port_cagr")),
            "benchmark_cagr": _num(attr.get("bench_cagr")),
            "alpha_annualized": _num(attr.get("alpha_annualized")),
            "benchmark_label": bench_label,
            "benchmark_source": bench_source,
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

def _is_reentry_opportunity(it: dict[str, Any]) -> bool:
    """True when an opportunity row is a re-entry candidate, not a staged watch.

    The queue's ``source``/``state`` are the primary signal; ``directive_label``
    is a legacy fallback (e.g. "Re-entry NEAR ENTRY — ADBE" has no RE_ENTER
    token but is unmistakably a re-entry). Watch chips must be the staged *watch*
    queue, not mislabeled re-entry rows.
    """
    if _str(it.get("source") or "").lower() == "reentry":
        return True
    state = _str(it.get("state") or "").upper()
    if state in {"READY TO REVIEW", "NEAR ENTRY", "OVERSOLD REVIEW"}:
        return True
    label = _str(it.get("directive_label") or "").upper()
    return any(m in label for m in ("RE_ENTER", "RE-ENTER", "REENTER", "RE-ENTRY", "NEAR ENTRY"))


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
        source = it.get("source")
        signal = _action_hint(it.get("directive_label"), it.get("verdict"))
        rec = {
            "symbol": symbol,
            "source": source,
            "signal": signal,
            "label": it.get("directive_label"),
        }
        if _is_reentry_opportunity(it):
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
        try:
            from scripts.lib.cio_decision_semantics import professional_label, is_pseudo_sector
            if is_pseudo_sector(o.get("sector")):
                continue
            rotation.append({
                "sector": o.get("sector"),
                "state": professional_label(o.get("state")) if o.get("state") else o.get("state"),
                "recommendation": professional_label(o.get("recommendation"))
                if o.get("recommendation") else o.get("recommendation"),
            })
        except Exception:
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
        "watch_total": len(watch),
        "reentry": reentry[:6],
        "reentry_total": len(reentry),
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
    capital_plan: Optional[dict[str, Any]] = None,
    source_refs: Optional[list[dict[str, Any]]] = None,
    validator_states: Optional[list[dict[str, Any]]] = None,
    run_ids: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Evidence / Audit drawer — internal codes, digests, run ids (not primary narrative)."""
    r = report or {}
    manifest = r.get("manifest") or {}
    plan = capital_plan or {}
    internal_codes: list[str] = []
    for fid in (r.get("checkpoint") or {}).get("fields_unavailable") or []:
        internal_codes.append(fid)
    # Surface process/raw enums only here
    for c in plan.get("portfolio_constraints") or []:
        if isinstance(c, dict) and c.get("kind"):
            internal_codes.append(str(c.get("kind")))

    return {
        "as_of": r.get("as_of") or _now_iso(now),
        "report_version": r.get("report_version") or OFFICE_HOME_VERSION,
        "authority": r.get("authority") or "READ_ONLY_ADVISORY",
        "source_sha": manifest.get("source_sha"),
        "manifest_hash": manifest.get("manifest_hash"),
        "facts_fingerprint": r.get("facts_fingerprint") or (r.get("view") or {}).get("facts_fingerprint"),
        "capital_plan_digest": plan.get("digest"),
        "plan_version": plan.get("plan_version"),
        "report_id": r.get("report_id"),
        "source_refs": source_refs or [],
        "validator_states": validator_states or [],
        "run_ids": run_ids or [],
        "internal_codes": internal_codes,
        "note": "Internal digests, run ids, and raw field codes live here — not in CIO NOW narrative.",
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
    plan = capital_plan or {}
    cio_now = build_cio_now(
        position_decisions=plan.get("position_decisions"),
        actions=actions,
        plans=plans,
        portfolio_value=_num(plan.get("portfolio_value_usd")),
    )
    capital_surface = build_capital_plan(plan)
    home = {
        "version": OFFICE_HOME_VERSION,
        "authority": "READ_ONLY_ADVISORY",
        "as_of": _now_iso(now),
        "cio_now": cio_now,
        "capital_plan": capital_surface,
        "posture": build_posture(
            capital_plan=plan,
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
            capital_plan=plan,
            source_refs=source_refs,
            validator_states=validator_states,
            run_ids=run_ids,
            now=now,
        ),
        # Phase 8 consistency anchors for report/Telegram alignment tests
        "consistency": {
            "decision_ids": list(cio_now.get("decision_ids") or []),
            "capital_plan_digest": capital_surface.get("plan_digest"),
            "plan_version": capital_surface.get("plan_version") or plan.get("plan_version"),
            "office_home_version": OFFICE_HOME_VERSION,
        },
    }
    # Phases 11–16: surface strategy/seasonality/research context (risk modifier only)
    sc = plan.get("strategy_context")
    if not sc:
        try:
            from scripts.lib.cio_seasonality_engine import build_seasonality_context
            from scripts.lib.cio_strategy_knowledge import (
                load_strategy_store,
                compose_strategy_context,
            )
            from scripts.lib.cio_research_retriever import retrieve_research_context
            season = plan.get("seasonality") or build_seasonality_context(now)
            research = plan.get("research_context") or retrieve_research_context(now)
            sc = compose_strategy_context(
                now=now,
                store=load_strategy_store(),
                seasonality=season,
                research_context=research,
            )
        except Exception as exc:
            sc = {"error": str(exc)[:160], "role": "risk_modifier_or_context"}
    home["strategy_context"] = sc
    home["seasonality"] = plan.get("seasonality") or (sc or {}).get("seasonality")
    home["research_context"] = plan.get("research_context") or (sc or {}).get("research_context")
    home["earmark_narrative"] = plan.get("earmark_narrative") or (
        (plan.get("account_capital_ledger") or {}).get("narrative")
    )
    # Phase 7 parity across plan decisions and CIO NOW cards
    try:
        from scripts.lib.cio_decision_semantics import decision_field_parity
        home["consistency"]["decision_field_parity"] = decision_field_parity(
            plan.get("position_decisions") or [],
            cio_now.get("decisions") or [],
        )
    except Exception as exc:
        home["consistency"]["decision_field_parity"] = {
            "ok": False, "error": str(exc)[:160],
        }
    home["operator_trust"] = build_operator_trust()
    return home


def build_operator_trust() -> dict[str, Any]:
    """Existing-page trust strip: Aegis last run, holdings reason, notify suppression.

    Fail-soft. Never invents a dashboard and never mutates broker/state.
    """
    return {
        "aegis_last_run": _trust_aegis(),
        "holdings": _trust_holdings(),
        "notification": _trust_notification(),
        "authority": "READ_ONLY_ADVISORY",
    }


def _trust_aegis() -> dict[str, Any]:
    from pathlib import Path
    roots = []
    try:
        from scripts.lib.maturity_control.store import resolve_root
        roots.append(resolve_root(None))
    except Exception:
        pass
    roots.append(Path(__file__).resolve().parents[2])
    for root in roots:
        for rel in (
            "data/runtime/aegis_evening_packet.json",
            "data/cio/aegis_evening_packet.json",
        ):
            p = root / rel
            if not p.is_file():
                continue
            try:
                import json
                pkt = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if not isinstance(pkt, dict):
                continue
            return {
                "available": True,
                "generated_at": pkt.get("generated_at"),
                "session_target": "isolated",
                "canonical_cio_source": pkt.get("canonical_cio_source"),
                "product_id": (pkt.get("cio") or {}).get("product_id"),
                "packet_chars": pkt.get("packet_chars"),
                "overflow": False,
            }
    return {
        "available": False,
        "session_target": "isolated",
        "note": "No Aegis evening packet on disk yet",
    }


def _trust_holdings() -> dict[str, Any]:
    try:
        from scripts.lib.holdings_sanity import validate_payload, REASON_VALID_COMPLETE
    except Exception:
        try:
            from holdings_sanity import validate_payload, REASON_VALID_COMPLETE
        except Exception as exc:
            return {"available": False, "reason_code": "DATA_UNAVAILABLE", "detail": str(exc)[:160]}
    from pathlib import Path
    try:
        from scripts.lib.maturity_control.store import resolve_root
        root = resolve_root(None)
    except Exception:
        root = Path(__file__).resolve().parents[2]
    doc = {}
    for rel in (
        "data/portfolios/state/holdings.json",
        "data/state/holdings.json",
    ):
        p = root / rel
        if p.is_file():
            import json
            try:
                doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                doc = {}
            if doc:
                break
    try:
        v = validate_payload(doc, last_good=doc if doc else None)
    except TypeError:
        try:
            v = validate_payload(doc)
        except Exception as exc:
            return {"available": False, "reason_code": "DATA_UNAVAILABLE", "detail": str(exc)[:160]}
    except Exception as exc:
        return {"available": False, "reason_code": "DATA_UNAVAILABLE", "detail": str(exc)[:160]}
    reason = getattr(v, "reason_code", None) or (v.get("reason_code") if isinstance(v, dict) else None)
    return {
        "available": True,
        "ok": bool(getattr(v, "ok", None) if not isinstance(v, dict) else v.get("ok")),
        "reason_code": reason or REASON_VALID_COMPLETE,
        "reason": getattr(v, "reason", None) if not isinstance(v, dict) else v.get("reason"),
        "total": getattr(v, "total", None) if not isinstance(v, dict) else v.get("total"),
    }


def _trust_notification() -> dict[str, Any]:
    try:
        from scripts.lib.cio_notification_signal import NotificationStateStore
        store = NotificationStateStore()
        rows = list((store.all_lineages() or {}).values())
    except Exception as exc:
        return {"available": False, "suppression_reason": "DATA_UNAVAILABLE", "detail": str(exc)[:160]}
    if not rows:
        return {"available": True, "suppression_reason": "none_on_record", "notification_class": None}
    rows.sort(key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
    latest = rows[0]
    return {
        "available": True,
        "notification_class": latest.get("notification_class"),
        "suppression_reason": latest.get("suppressed_reason") or "none",
        "decision_id": latest.get("decision_id"),
        "updated_at": latest.get("updated_at") or latest.get("created_at"),
    }
