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


def suppress_untrusted_sizing(card: dict[str, Any]) -> dict[str, Any]:
    """Remove financial-looking sizing whenever current action is blocked.

    Standing views remain visible for review, but stale/conflicted truth may not
    render a dollar change, target, trim amount, scenario, or sizing prose.
    """
    _, blocking = _canonical_action(card)
    if not blocking:
        card["sizing_suppressed"] = False
        card["sizing_suppression_reason"] = None
        return card
    for field in (
        "delta_usd", "recommended_delta_usd", "target_weight_pct",
        "trim_to_clear_fire_usd", "trim_to_policy_usd", "scenario_trim_usd",
        "sizing_method", "sizing_objective",
    ):
        card[field] = None
    card["sizing_suppressed"] = True
    card["sizing_suppression_reason"] = str(blocking)
    return card


def build_cio_now(
    *,
    position_decisions: Optional[list[dict[str, Any]]] = None,
    actions: Optional[list[dict[str, Any]]] = None,
    plans: Optional[list[dict[str, Any]]] = None,
    all_open_plans: Optional[list[dict[str, Any]]] = None,
    portfolio_value: Optional[float] = None,
) -> dict[str, Any]:
    """CIO NOW — at most 5 investment decision cards + disjoint attention KPIs.

    Phase 4 attention model (no double-count across KPI buckets):
      INVESTMENT DECISIONS — true InvestmentDecision objects needing attention
      WORKFLOW ACTIONS     — open action-ledger items only
      OPEN PLANS           — durable plans still open, counted from the FULL
                             store (`all_open_plans`), not the card window.
                             `plans` is the 12-row CIO NOW window; counting the
                             KPI off it reported 12 against 458 real open plans,
                             the same error as the `with_plan=1` coverage bug.
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
                "symbol_thesis_id": d.get("symbol_thesis_id") or raw.get("symbol_thesis_id"),
                "symbol_thesis_version": d.get("symbol_thesis_version") or raw.get("symbol_thesis_version"),
            }
            investment_pool.append(suppress_untrusted_sizing(card))
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
            card = {
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
                    {"code": "AGREE", "label": "Agree"},
                    {"code": "DISAGREE", "label": "Disagree"},
                    {"code": "DEFER", "label": "Defer"},
                    {"code": "NEED_DATA", "label": "Need data"},
                    {"code": "NO_LONGER_RELEVANT", "label": "No longer relevant"},
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
                "symbol_thesis_id": d.get("symbol_thesis_id"),
                "symbol_thesis_version": d.get("symbol_thesis_version"),
            }
            investment_pool.append(suppress_untrusted_sizing(card))

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
    # KPI counts the durable store; cards still come from `plans`.
    if all_open_plans:
        store_open = [p for p in all_open_plans
                      if isinstance(p, dict) and _plan_is_open(p)]
        if len(store_open) > len(open_plans):
            open_plans = store_open

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
        # The cash block's own evidence clock. The page-level stamp is when the
        # surface was composed; these dollars can be much older, and on the live
        # book they span 27 days. Never let the reader infer age from the frame.
        "cash_as_of": p.get("cash_as_of") or {
            "as_of": None, "unstamped": True,
            "note": "cash age not supplied by the plan; do not read the page "
                    "stamp as the age of these dollars",
        },
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
# Coverage (Wave 2 slices 08 / 11) + Surface A reentry overlay (slice 10)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


# Wave 2 slice 12b — situation types that count as "this held name has an open
# plan". S0 operator chatter and S7 watch promotion are not position coverage.
COVERAGE_PLAN_SITUATION_TYPES = (
    "S1_POSITION_LIFECYCLE",
    "S3_REENTRY_CANDIDATE",
    "S5_CASH_DEPLOYMENT",
    "S6_CONCENTRATION_OR_DISPOSITION",
)


def build_office_coverage(
    *,
    holdings_thesis_coverage: Optional[dict[str, Any]] = None,
    watch_block_summary: Optional[dict[str, Any]] = None,
    case_summaries: Optional[dict[str, Any]] = None,
    reentry: Optional[dict[str, Any]] = None,
    plans: Optional[list[Any]] = None,
    coverage_plans: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Class D office coverage counts from existing op/product keys.

    Fail-soft zeros. Never invents thesis, prices, or READY/NEAR. Prefer
    holdings_thesis_coverage / watch_block_summary / case_summaries / reentry
    counts over new collectors or routes.

    ``held`` / ``held_n`` and ``with_thesis`` / ``thesis_count`` are aliases so
    the CC card can show thesis_count/held_n. After Wave 2 slice 12a they carry
    the non-dust held universe; SCHG dust is excluded, not silently counted.

    Wave 2 slice 12b — ``with_plan`` counts open S1/S3/S5/S6 plans on non-dust
    held tickers. It reads ``coverage_plans`` (the whole open-plan store) when
    the caller supplies it, and only falls back to ``plans`` -- which on
    /v3/cio/home is a 12-row UI window -- when it does not. Counting against
    that window is what produced with_plan=1 against 575 open plans. The fix is
    the counter's input; no plan is minted to move the number.
    """
    htc = holdings_thesis_coverage if isinstance(holdings_thesis_coverage, dict) else {}
    wbs = watch_block_summary if isinstance(watch_block_summary, dict) else {}
    cases = case_summaries if isinstance(case_summaries, dict) else {}
    re = reentry if isinstance(reentry, dict) else {}
    re_counts = re.get("counts") if isinstance(re.get("counts"), dict) else {}

    held_n = _safe_int(htc.get("held_n"))
    thesis_count = _safe_int(htc.get("current_n"))
    # Item 118: carry the three dates through so the card can say which one a
    # number came from. Positions, basis and price are dated separately.
    cost_basis_as_of = htc.get("cost_basis_as_of")
    positions_as_of = htc.get("positions_as_of")
    priced_as_of = htc.get("priced_as_of")

    held_syms = {
        _str(i.get("symbol")).upper()
        for i in (htc.get("items") or [])
        if isinstance(i, dict) and i.get("symbol")
    }
    # Dust is not a hold: it can neither need a plan nor supply one (slice 12a).
    dust_syms = {
        _str(s).upper() for s in (htc.get("dust_tickers") or []) if s
    }
    held_syms -= dust_syms

    plan_rows = coverage_plans if coverage_plans is not None else (plans or [])
    plan_source = "open_plan_store" if coverage_plans is not None else "home_plan_window"
    plan_held: set[str] = set()
    research_held: set[str] = set()
    counted_open = 0
    for p in plan_rows:
        if not isinstance(p, dict):
            continue
        if not _plan_is_open(p):
            continue
        if _str(p.get("situation_type")) not in COVERAGE_PLAN_SITUATION_TYPES:
            continue
        counted_open += 1
        psyms = {
            _str(s).upper()
            for s in (p.get("symbols") or [])
            if s
        }
        hit = psyms & held_syms
        if not hit:
            continue
        plan_held |= hit
        if p.get("hermes_result_id"):
            research_held |= hit

    # Prefer ready_count (READY+NEAR); fall back to named lists.
    watch_ready = _safe_int(wbs.get("ready_count"))
    if watch_ready <= 0:
        ready_syms = wbs.get("ready_symbols") if isinstance(wbs.get("ready_symbols"), list) else []
        near_syms = wbs.get("near_symbols") if isinstance(wbs.get("near_symbols"), list) else []
        watch_ready = len([s for s in list(ready_syms) + list(near_syms) if s])
    watch_block = _safe_int(wbs.get("count"))
    reentry_near = _safe_int(re_counts.get("NEAR"))
    with_case = _safe_int(cases.get("count"))

    return {
        "held": held_n,
        "held_n": held_n,
        "with_plan": len(plan_held),
        "with_plan_symbols": sorted(plan_held),
        "with_plan_source": plan_source,
        "open_plans_considered": counted_open,
        "with_thesis": thesis_count,
        "thesis_count": thesis_count,
        "with_research": len(research_held),
        "with_case_summary": with_case,
        "watch_ready": watch_ready,
        "watch_block": watch_block,
        "reentry_near": reentry_near,
        "cost_basis_as_of": cost_basis_as_of,
        "positions_as_of": positions_as_of,
        "priced_as_of": priced_as_of,
        "class": "D",
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "note": (
            "Aggregated from holdings_thesis_coverage, open S1/S3/S5/S6 plans ∩ "
            "non-dust held, case_summaries.count, watch_block_summary, Surface A "
            "reentry.counts. Fail-soft zeros. No Telegram."
        ),
    }


def build_notification_block(
    plans: Optional[list[dict[str, Any]]] = None,
    *,
    cap: int = 10,
    now: Optional[Any] = None,
) -> dict[str, Any]:
    """Wave 3E — render NotificationPolicy decisions as a Command Center block.

    **Scope, per the operator: CC block only. No Telegram producer, INTERDICT
    stays on, `CIO_SITUATION_NOTIFY` stays 0.**

    That makes this pure rendering. It reads the decisions `NotificationPolicy@v1`
    already computes and displays them; it constructs no message, selects no
    adapter, and reaches no channel. `would_send` is False on every row and
    `producer` is null — a test asserts both, and asserts this module gained no
    delivery import.

    The suppressed count matters as much as the surfaced one. A notification
    surface that shows only what fired teaches the reader that nothing else was
    considered; showing 460 suppressed with reasons is what makes 4 credible.
    """
    rows = list(plans or [])
    try:
        from scripts.lib import cio_notification_policy as _policy
    except Exception as exc:                                    # noqa: BLE001
        return {
            "schema": "CIONotificationBlock@v1",
            "available": False,
            "reason": "policy_unavailable",
            "detail": str(exc)[:160],
            "telegram_sent": False,
            "would_send_any": False,
            "producer": None,
            "authority": "READ_ONLY_ADVISORY",
        }

    seen: set[tuple] = set()
    decisions: list[dict[str, Any]] = []
    for p in rows:
        if not isinstance(p, dict):
            continue
        if str(p.get("status") or "") not in {"draft", "proposed"}:
            continue
        syms = p.get("symbols") or []
        key = (str(p.get("situation_type") or ""), syms[0] if syms else None)
        dup = key in seen
        d = _policy.decide(p, duplicate_subject=dup, now=now)
        # Only a row that actually surfaces may claim the subject slot.
        #
        # Claiming it unconditionally let a SUPPRESSED row shadow a real one:
        # the first ('S6…','AMANX') row is material=False, so it suppressed as
        # not_material and still took the slot — and a later material AMANX S6
        # then suppressed as duplicate_subject. A concentration fire vanished
        # because a non-material row happened to be iterated first.
        if d.get("decision") != _policy.SUPPRESSED:
            seen.add(key)
        decisions.append(d)

    surfaced = [d for d in decisions
                if d.get("decision") == _policy.COMMAND_CENTER_ONLY]
    digest = [d for d in decisions if d.get("decision") == _policy.DIGEST]
    immediate = [d for d in decisions if d.get("decision") == _policy.IMMEDIATE]

    by_reason: dict[str, int] = {}
    for d in decisions:
        if d.get("decision") == _policy.SUPPRESSED:
            r = str(d.get("reason") or "unknown")
            by_reason[r] = by_reason.get(r, 0) + 1

    def _row(d: dict[str, Any]) -> dict[str, Any]:
        return {
            "plan_id": d.get("plan_id"),
            "situation_type": d.get("situation_type"),
            "decision": d.get("decision"),
            "reason": d.get("reason"),
            "notification_id": d.get("notification_id"),
            "would_send": False,
        }

    env = _policy.notify_env_state()
    # S0 rows are visible on the product even though the policy suppresses
    # notifying about them — the operator should see their own turns landed.
    s0_rows = [
        {"plan_id": p.get("plan_id"),
         "symbols": p.get("symbols") or [],
         "status": p.get("status"),
         "title": str(p.get("title") or "")[:80]}
        for p in rows
        if isinstance(p, dict)
        and str(p.get("situation_type") or "").startswith("S0")
        and str(p.get("status") or "") in {"draft", "proposed"}
    ]
    return {
        "schema": "CIONotificationBlock@v1",
        "s0_operator_turns": s0_rows[:cap],
        "s0_open_n": len(s0_rows),
        "available": True,
        "authority": "READ_ONLY_ADVISORY",
        "financial_action": False,
        "memory_behavior_influence": 0,
        # Scope declarations. Wave 3E is rendering only.
        "producer": None,
        "channel": "command_center",
        "telegram_sent": False,
        "would_send_any": False,
        "notify_enabled": bool(env.get("notify_enabled")),
        "interdicted": bool(env.get("interdicted")),
        "considered": len(decisions),
        "surfaced_n": len(surfaced),
        "items": [_row(d) for d in surfaced[:cap]],
        "digest_n": len(digest),
        "immediate_n": len(immediate),
        "suppressed_n": sum(by_reason.values()),
        "suppressed_by_reason": dict(
            sorted(by_reason.items(), key=lambda kv: -kv[1])),
        "cap": cap,
        "note": ("Command Center only. No message is produced or sent; "
                 "suppressed counts are shown so the surfaced few are legible "
                 "against everything that was considered."),
    }


def build_agent_brief_panel() -> dict[str, Any]:
    """What the agent did, on the Command Center — the same artifact as the
    daily Telegram brief, from one producer.

    Reporting only. Two surfaces rendering the same quantity from two producers
    is the defect P9.3 documented; this reads `cio_agent_brief.build_brief` and
    re-words nothing, so the panel and the message cannot drift.
    """
    try:
        from scripts.lib.cio_agent_brief import build_brief, SCHEMA
    except Exception:
        try:
            from lib.cio_agent_brief import build_brief, SCHEMA  # type: ignore
        except Exception as exc:
            return {
                "schema": "CIOAgentBrief@v1",
                "authority": "READ_ONLY_ADVISORY",
                "available": False,
                "reason": f"{type(exc).__name__}: {str(exc)[:120]}",
            }
    try:
        b = build_brief()
    except Exception as exc:
        return {
            "schema": SCHEMA,
            "authority": "READ_ONLY_ADVISORY",
            "available": False,
            "reason": f"{type(exc).__name__}: {str(exc)[:120]}",
        }
    b["available"] = True
    b["surface"] = "command_center"
    b["provenance_note"] = (
        "All counts deterministic (class D). Prose is template (class T). "
        "No judgment was exercised in this panel."
    )
    return b


def build_reentry_book_labels() -> dict[str, Any]:
    """Name both re-entry books on /v3/cio/home. Labelling is not merging.

    The canonical definitions already live in `cio_reentry_surface_labels` and
    each producer stamps its own book — `cio_investment_product.build_reentry_book`
    with SURFACE_A, `cio_desk_depth.build_reentry_book` with SURFACE_B. Neither
    book reaches this payload, though, so a reader here saw two re-entry counts
    with no way to tell which question each answers. That is how two books get
    merged in someone's head while the code keeps them apart.

    Read from the canonical module, never re-worded here: a second copy of the
    label text is a second definition waiting to drift.
    """
    try:
        from scripts.lib.cio_reentry_surface_labels import SURFACE_A, SURFACE_B
    except Exception as exc:
        return {
            "schema": "CIOReentryBookLabels@v1",
            "authority": "READ_ONLY_ADVISORY",
            "available": False,
            "reason": type(exc).__name__,
            "merged": False,
            "class": "D",
        }

    def _view(sfc: dict[str, Any]) -> dict[str, Any]:
        return {
            "surface": sfc["surface"],
            "surface_name": sfc["name"],
            "scope": sfc["scope"],
            "question": sfc["question"],
            "precedence": sfc["precedence"],
            "not_this_book": sfc["not_this_book"],
            "producer": sfc["producer"],
            "class": sfc["class"],
        }

    return {
        "schema": "CIOReentryBookLabels@v1",
        "authority": "READ_ONLY_ADVISORY",
        "available": True,
        "merged": False,
        "a": _view(SURFACE_A),
        "b": _view(SURFACE_B),
        "class": "D",
        "note": (
            "Two independent books with different questions (#584 / P9.3). "
            "Precedence is not a winner — each is authoritative only for its "
            "own question. Never combined."
        ),
    }


def overlay_surface_a_reentry_on_opportunities(
    opportunities: dict[str, Any],
    reentry: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Overlay Surface A NEAR/REENTER counts onto home opportunities.

    Does **not** merge books. Queue-sourced ``reentry`` chips stay pipe 1;
    Surface A ``reentry_book`` / operator ``reentry`` is pipe 2. When Surface A
    names are nonempty, ``reentry_total`` and ``surface_a_*`` keys are non-zero
    even if the queue pipe is empty.
    """
    opp = dict(opportunities or {})
    re = reentry if isinstance(reentry, dict) else {}
    names = re.get("names") if isinstance(re.get("names"), list) else None
    sa_count = _safe_int(re.get("count"))
    if names is not None and sa_count <= 0:
        sa_count = len(names)
    re_counts = re.get("counts") if isinstance(re.get("counts"), dict) else {}
    sa_near = _safe_int(re_counts.get("NEAR"))
    sa_reenter = _safe_int(re_counts.get("REENTER"))
    queue_total = _safe_int(opp.get("reentry_total"))

    opp["queue_reentry_total"] = queue_total
    opp["surface_a_reentry_count"] = sa_count
    opp["surface_a_reentry_near"] = sa_near
    opp["surface_a_reentry_reenter"] = sa_reenter
    # `reentry_total` used to be one of THREE quantities depending on the day's
    # data -- NEAR+REENTER overlay, else the full Surface A book, else the queue
    # pipe -- while sitting in the field position that reads as the total of the
    # list above it, and `reentry_pipes` did not mention it. On a money surface a
    # number whose meaning moves with the data is worse than no number.
    #
    # It is now bound to ONE book: the Surface A re-entry book count, always. The
    # actionable subset is its own named field rather than a value that
    # sometimes replaces the total, and every field is in the pipes map.
    opp["reentry_total"] = sa_count
    opp["reentry_actionable"] = sa_near + sa_reenter
    opp["reentry_pipes"] = {
        "queue": "opportunities.reentry / queue_reentry_total",
        "surface_a": "surface_a_reentry_* from operator_product.reentry / reentry_book",
        "reentry_total": "surface_a_reentry_count — the Surface A book, always; "
                         "not the queue pipe and not the actionable subset",
        "reentry_actionable": "surface_a_reentry_near + surface_a_reentry_reenter "
                              "— the subset of reentry_total that is actionable now",
        "queue_reentry_total": "the queue pipe; a different population, never summed "
                               "with reentry_total",
        "merged": False,
        "note": "Dual pipes labeled not merged (Wave 1 slice 3 / Wave 2 slice 10). "
                "reentry_total is bound to one book and no longer branches.",
    }
    return opp


# ─────────────────────────────────────────────────────────────────────────────
# Slice C — the record's narrative, rendered
# ─────────────────────────────────────────────────────────────────────────────
#
# `cio_run` stays a DETERMINISTIC_PRODUCT. The narrative blob is an INPUT this
# composer renders, exactly like a number: the agent wrote the prose earlier in
# its own governed lane and the record carried it forward. Nothing below calls
# a model, and `test_cio_cc_record_narrative_slice_c.py` asserts this module
# imports no delivery/LLM module.
#
# Every read fails SOFT. A missing or empty store must still produce a payload —
# a blank page is worse than a stale one, and a page that empties itself when
# memory is missing teaches the reader that memory is optional.

RECORD_NARRATIVE_SECTIONS = ("book", "watch", "reentry", "cash", "sector")


def resolve_record_store(record_store: Any = None) -> Any:
    """The InstrumentRecord store, or None. Never raises."""
    if record_store is not None:
        return record_store
    try:
        from scripts.lib.cio_instrument_record import InstrumentRecordStore
        return InstrumentRecordStore()
    except Exception:                                            # noqa: BLE001
        return None


def _narrative_is_clean(text: Any) -> bool:
    """A record is agent-written prose; it does not get to smuggle an order in.

    The guard that protects the cash letter also runs over row narratives. A
    record that trips it is DROPPED back to the deterministic line rather than
    raising, because one poisoned row must not blank the whole desk.
    """
    try:
        from scripts.lib.cio_record_narrative import assert_no_instruction
        assert_no_instruction(text)
        return True
    except Exception:                                            # noqa: BLE001
        return False


def _row_narrative(store: Any, keys: tuple[str, ...], fallback_what: str) -> dict[str, Any]:
    """Prefer the record's cc_narrative; fall back deterministically."""
    if store is not None:
        try:
            from scripts.lib.cio_record_narrative import narrative_for
        except Exception:                                        # noqa: BLE001
            narrative_for = None                                 # type: ignore[assignment]
        if narrative_for is not None:
            for key in keys:
                try:
                    nar = narrative_for(key, store=store)
                except Exception:                                # noqa: BLE001
                    nar = None
                if nar and _str(nar.get("what")).strip():
                    if _narrative_is_clean(nar.get("what")):
                        out = dict(nar)
                        out["narrative_source"] = "record"
                        # B5 — writer names the author, not the last hand.
                        out["author"] = out.get("writer") or out.get("author") or "record"
                        out["writer"] = out["author"]
                        return out
                    return {
                        "subject_key": key,
                        "what": fallback_what,
                        "writer": "deterministic_fallback",
                        "author": "deterministic_fallback",
                        "from_record": False,
                        "narrative_source": "deterministic",
                        "record_refused": "instruction_in_narrative",
                    }
    return {
        "subject_key": keys[0] if keys else None,
        "what": fallback_what,
        "writer": "deterministic_fallback",
        "author": "deterministic_fallback",
        "from_record": False,
        "narrative_source": "deterministic",
    }


def attach_record_narratives(home: dict[str, Any], store: Any) -> dict[str, Any]:
    """Attach `cc_narrative` to the CC sections the spec names.

    position/book row · watch row · re-entry row · sector row. (The SLEEVE:CASH
    letter is built separately by `build_cash_letter_section`, which enforces a
    much tighter shape.) Returns a small coverage object so the page can say how
    much of what it shows came from memory rather than from a template.
    """
    try:
        from scripts.lib.cio_instrument_record import subject_key as _sk
    except Exception:                                            # noqa: BLE001
        def _sk(kind: str, name: str) -> str:                    # type: ignore[misc]
            return f"{str(kind).upper()}:{str(name).strip().upper()}"

    counts = {k: {"rows": 0, "from_record": 0} for k in RECORD_NARRATIVE_SECTIONS}

    def _tally(section: str, nar: dict[str, Any]) -> None:
        counts[section]["rows"] += 1
        if nar.get("from_record"):
            counts[section]["from_record"] += 1

    # Position / book rows — HELD first, EXIT for a name already being unwound.
    for row in (home.get("cio_now") or {}).get("decisions") or []:
        if not isinstance(row, dict):
            continue
        sym = _str(row.get("symbol")).upper()
        if not sym:
            continue
        stance = _human_stance(row.get("stance") or row.get("action"))
        nar = _row_narrative(
            store,
            (_sk("HELD", sym), _sk("EXIT", sym)),
            f"{sym}: {stance}. No record narrative attached yet.",
        )
        row["cc_narrative"] = nar
        row["narrative_source"] = nar.get("narrative_source")
        _tally("book", nar)

    opp = home.get("opportunities") or {}
    for section, section_keys in (
        ("watch", ("WATCH", "HELD")),
        ("reentry", ("EXIT", "WATCH", "HELD")),
    ):
        for row in opp.get(section) or []:
            if not isinstance(row, dict):
                continue
            sym = _str(row.get("symbol")).upper()
            if not sym:
                continue
            signal = _str(row.get("signal") or row.get("label")) or "no signal"
            nar = _row_narrative(
                store,
                tuple(_sk(k, sym) for k in section_keys),
                f"{sym}: {signal}. No record narrative attached yet.",
            )
            row["cc_narrative"] = nar
            row["narrative_source"] = nar.get("narrative_source")
            _tally(section, nar)

    for row in (home.get("posture") or {}).get("sector_tilts") or []:
        if not isinstance(row, dict):
            continue
        name = _str(row.get("sector")).strip()
        if not name:
            continue
        state = _str(row.get("state")) or "no state"
        nar = _row_narrative(
            store,
            (_sk("SECTOR", name),),
            f"{name}: {state}. No record narrative attached yet.",
        )
        row["cc_narrative"] = nar
        row["narrative_source"] = nar.get("narrative_source")
        _tally("sector", nar)

    letter = home.get("cash_letter") or {}
    counts["cash"]["rows"] = 1 if letter else 0
    counts["cash"]["from_record"] = 1 if letter.get("from_record") else 0

    rows_n = sum(c["rows"] for c in counts.values())
    rec_n = sum(c["from_record"] for c in counts.values())
    # A store object that reads an absent file is not the same as memory being
    # present, and reporting only "available" would hide an empty spine.
    try:
        store_records = len(store.all()) if store is not None else 0
    except Exception:                                            # noqa: BLE001
        store_records = 0
    return {
        "schema": "CCRecordNarrativeCoverage@v1",
        "sections": counts,
        "rows": rows_n,
        "from_record": rec_n,
        "from_deterministic_fallback": rows_n - rec_n,
        "store_available": store is not None,
        "store_records": store_records,
        "authority": "READ_ONLY_ADVISORY",
        "memory_behavior_influence": 0,
        "product": "DETERMINISTIC_PRODUCT",
        "note": (
            "CC prefers InstrumentRecord.cc_narrative and falls back "
            "deterministically. The composer renders prose; it never calls a model."
        ),
    }


def build_cash_letter_section(
    store: Any,
    *,
    capital_plan: Optional[dict[str, Any]] = None,
    seasonality: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """The SLEEVE:CASH letter. Required on /v3/cio even though notify is off.

    Cash is the $630k question and the single easiest place for an advisory
    surface to drift into instruction, so the letter is on the page whether or
    not anything is being delivered anywhere.
    """
    try:
        from scripts.lib.cio_instrument_record import CASH_SLEEVE
        from scripts.lib.cio_record_narrative import build_cash_letter
    except Exception as exc:                                     # noqa: BLE001
        return {
            "schema": "CashSleeveLetter@v1",
            "available": False,
            "reason": f"module_unavailable: {str(exc)[:120]}",
            "authority": "READ_ONLY_ADVISORY",
        }
    rec = None
    if store is not None:
        try:
            rec = store.load(CASH_SLEEVE)
        except Exception:                                        # noqa: BLE001
            rec = None
    try:
        letter = build_cash_letter(
            rec, capital_plan=capital_plan, seasonality=seasonality, now=now)
    except Exception as exc:                                     # noqa: BLE001
        # A record that trips the instruction guard loses its prose, not the
        # letter. The reader still gets the cash figure and the next look-date.
        try:
            letter = build_cash_letter(
                None, capital_plan=capital_plan, seasonality=seasonality, now=now)
            letter["record_refused"] = str(exc)[:160]
        except Exception:                                        # noqa: BLE001
            return {
                "schema": "CashSleeveLetter@v1",
                "available": False,
                "reason": str(exc)[:160],
                "authority": "READ_ONLY_ADVISORY",
            }
    return _stamp_cash_letter_provenance(letter, capital_plan=capital_plan)


def _stamp_cash_letter_provenance(
    letter: dict[str, Any],
    *,
    capital_plan: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """B4/B5 — letter age is cash evidence, writer means author.

    `build_cash_letter` historically stamped `as_of=now` (composition). The
    dollars can be weeks older. Prefer capital_plan.cash_as_of (oldest
    contributing balance). Dollar fields are left untouched.
    """
    out = dict(letter or {})
    author = out.get("writer") or out.get("author") or "deterministic_fallback"
    out["author"] = author
    out["writer"] = author  # AGENTS §9.2 — writer names the author
    evidence = (capital_plan or {}).get("cash_as_of")
    if isinstance(evidence, dict) and evidence.get("as_of"):
        out["composition_as_of"] = out.get("as_of")
        out["as_of"] = evidence.get("as_of")
        out["cash_as_of"] = evidence
        out["as_of_source"] = "cash_evidence_oldest_balance"
    else:
        out["as_of_source"] = out.get("as_of_source") or "composition_time"
        out.setdefault(
            "as_of_note",
            "cash evidence age not supplied; do not read composition time as "
            "the age of these dollars",
        )
    out["model_produced"] = False
    return out


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
    coverage_plans: Optional[list[dict[str, Any]]] = None,
    graph_impact: Optional[dict[str, Any]] = None,
    source_refs: Optional[list[dict[str, Any]]] = None,
    validator_states: Optional[list[dict[str, Any]]] = None,
    run_ids: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
    operator_product: Optional[dict[str, Any]] = None,
    record_store: Optional[Any] = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    plan = capital_plan or {}
    cio_now = build_cio_now(
        position_decisions=plan.get("position_decisions"),
        actions=actions,
        plans=plans,
        all_open_plans=coverage_plans,
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
    # Composition does not hunt files. API wrapper injects the canonical product.
    # B3: a bare except that served the unrendered product used to still stamp
    # `canonical_cio_source` — a provenance label for a path that did not run.
    # Stamp only when command_center_view actually rendered.
    if operator_product is None:
        home["operator_product"] = {
            "source": "cio.operator_product.current",
            "loaded": False,
            "note": "injected by API wrapper; composition itself does not hunt files",
        }
        # No rendered product → no canonical stamp.
    else:
        try:
            from scripts.lib.cio_operator_renderers import command_center_view
            home["operator_product"] = command_center_view(operator_product)
            home["canonical_cio_source"] = "cio.operator_product.current"
        except Exception as _render_exc:
            home["operator_product"] = {
                "source": "cio.operator_product.current",
                "loaded": False,
                "render_error": str(_render_exc)[:200],
                "note": "command_center_view failed; unrendered product is not stamped canonical",
                "raw_available": True,
            }
            # Deliberately omit canonical_cio_source — failure must reach the
            # surface as absence of the stamp, not a false provenance claim.
    op = operator_product if isinstance(operator_product, dict) else {}
    home["earnings"] = list(op.get("earnings") or [])[:12]
    home["new_position_if"] = list(op.get("new_position_if") or [])[:8]
    home["holdings_thesis_coverage"] = op.get("holdings_thesis_coverage") if isinstance(op.get("holdings_thesis_coverage"), dict) else {}
    home["surface_a_status"] = op.get("surface_a_status") if isinstance(op.get("surface_a_status"), dict) else {}
    home["watch_block_summary"] = (
        op.get("watch_block_summary") if isinstance(op.get("watch_block_summary"), dict) else {}
    )
    home["cash"] = op.get("cash") or {}
    # B5 — demote constant standing-policy text so home does not render it as
    # situation guidance. Prefer OP's already-redacted temperament.
    temp = op.get("temperament") or op.get("macro") or {}
    if isinstance(temp, dict):
        temp = dict(temp)
        if temp.get("portfolio_implication") and not temp.get(
            "portfolio_implication_is_guidance"
        ):
            temp.setdefault(
                "standing_policy_template", temp.get("portfolio_implication")
            )
            temp["portfolio_implication"] = None
            temp["portfolio_implication_is_guidance"] = False
            temp["portfolio_implication_role"] = "standing_policy_template"
        # Cash on temperament shares the cash block clock when OP stamped it.
        if isinstance(home["cash"], dict) and home["cash"].get("cash_as_of"):
            temp.setdefault("cash_as_of", home["cash"]["cash_as_of"])
    home["temperament"] = temp
    home["case_summaries"] = op.get("case_summaries") or op.get("research_cases") or {
        "banner": "A-context · NON_AUTHORITATIVE · does not change action",
        "class": "A",
        "count": 0,
        "items": [],
    }
    home["block_as_of"] = op.get("block_as_of") or {
        "cash": (home["cash"] or {}).get("as_of") if isinstance(home["cash"], dict) else None,
        "product_composition": op.get("as_of"),
        "home_composition": home.get("as_of"),
        "note": (
            "home.as_of is request composition time; cash age is home.cash.as_of "
            "/ capital_plan.cash_as_of (oldest contributing balance)."
        ),
    }
    home["provenance_footer"] = op.get("provenance_footer") or {
        "model_produced": False,
        "classes": "D counts/sums · T templates · A case-summary context",
        "writer_means": "author",
        "note": (
            "Office home is a deterministic composition. No model produced "
            "this page; model/process telemetry belongs below the fold only "
            "when a model actually ran."
        ),
    }
    home["model_produced"] = False
    # Wave 2 slice 10: overlay Surface A reentry counts onto opportunities
    # without merging queue chips with the Surface A book (dual pipes).
    home["opportunities"] = overlay_surface_a_reentry_on_opportunities(
        home.get("opportunities") or {},
        op.get("reentry") if isinstance(op.get("reentry"), dict) else {},
    )
    # Wave 2C items 131/132: both books name themselves on /home. The labels
    # existed on the built product but never reached this payload, so a reader
    # here could see two reentry numbers and no way to tell which question each
    # answers. Copied, never combined — `merged` stays false.
    home["reentry_books"] = build_reentry_book_labels()
    # Wave 2 slices 08/11: Class D coverage object on /v3/cio/home.
    home["coverage"] = build_office_coverage(
        holdings_thesis_coverage=home.get("holdings_thesis_coverage"),
        watch_block_summary=home.get("watch_block_summary"),
        case_summaries=home.get("case_summaries") if isinstance(home.get("case_summaries"), dict) else {},
        reentry=op.get("reentry") if isinstance(op.get("reentry"), dict) else {},
        plans=plans,
        coverage_plans=coverage_plans,
    )
    # Wave 2 slice 16: 1-hop same-sector context, S6 names only. Computed by the
    # caller that already holds plans + holdings; when a caller does not compute
    # it the key says so rather than going quietly missing.
    home["graph_impact"] = graph_impact if isinstance(graph_impact, dict) else {
        "schema": "CIOGraphImpactS6@v1",
        "available": False,
        "reason": "not_computed_by_this_caller",
        "scope": "S6_CONCENTRATION_OR_DISPOSITION names only",
        "items": {},
        "attached_n": 0,
        "class": "D",
        "authority": "READ_ONLY_ADVISORY",
    }
    # Wave 3E: the notification decisions, rendered. No producer, no channel.
    #
    # Fed from `coverage_plans` — the FULL open store — not `plans`, which is
    # the 12-row CIO NOW window. Reading the window made the block report
    # "suppressed_n: 12" against 450 real open plans, which is the same class
    # of error as showing only the survivors: a count that looks like the whole
    # picture and is not. NOW stays capped at 5 cards; the block is not a card.
    home["notifications"] = build_notification_block(
        coverage_plans if coverage_plans else plans)
    # Slice C: the persistent spine reaches the page.
    #
    # The record's own prose is PREFERRED for the position/book row, the watch
    # row, the re-entry row, the SLEEVE:CASH letter and the sector row, with a
    # deterministic line behind each one. This is a render of an INPUT, not a
    # model call — `cio_run` stays DETERMINISTIC_PRODUCT.
    #
    # The cash letter is unconditional. It is required on /v3/cio even though
    # notify is off, because the $630k question is answered on the page, not in
    # a channel.
    _store = resolve_record_store(record_store)
    home["cash_letter"] = build_cash_letter_section(
        _store,
        capital_plan=plan,
        seasonality=home.get("seasonality"),
        now=now,
    )
    try:
        from scripts.lib.cio_record_narrative import record_narratives
        home["instrument_narratives"] = record_narratives(_store) if _store else {}
    except Exception:                                            # noqa: BLE001
        home["instrument_narratives"] = {}
    home["record_narrative_coverage"] = attach_record_narratives(home, _store)
    home["telegram_sent"] = False
    home["delivery"] = "dashboard"
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
