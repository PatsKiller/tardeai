"""redeploy_decision — readiness states, decision scorecard, recommendation, PM memo.

The semantic-integrity contract (operator review 2026-07-14):
  - readiness is a governed state machine — OPERATOR_READY requires oversight PASS on majors;
    pending oversight renders ANALYTICS_READY, never operator-ready.
  - plan ranking is a transparent 10-dimension scorecard (visible, versioned weights) — never
    one opaque composite.
  - the system must output a plain-language recommendation: primary, alternatives with
    choose-when conditions, and do-not-choose with reasons.
Advisory only. Nothing here can place, size, or submit a broker order.
"""
from __future__ import annotations

from typing import Any

DECISION_POLICY_VERSION = "decision_1.1.0"
DECISIVE_SCORE_GAP = 2.0  # below this: NO DECISIVE WINNER; documented tie-breaker applies

# ── readiness state machine (Phase 2) ────────────────────────────────────────

READINESS_STATES = [
    "DRAFT", "DATA_INCOMPLETE", "QUOTES_STALE", "OVERSIGHT_PENDING", "OVERSIGHT_FAILED",
    "ANALYTICS_READY", "OPERATOR_READY", "OPERATOR_SELECTED", "OPERATOR_LOCKED",
    "IMPLEMENTATION_IN_PROGRESS", "COMPLETED", "DISMISSED",
]


def readiness_state(plan: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute the governed readiness state for one plan.

    ctx: {is_major, settled, reconciles, analytics_exist (pro-forma+performance+lookthrough),
          memo_exists, audit_exists, p0_warnings: [..], locked, selected, fills_recorded}
    Returns {state, reasons, operator_ready, display}.
    """
    reasons: list[str] = []
    legs = [l for l in (plan.get("legs") or []) if not l.get("is_reserve")]
    fin = plan.get("financials") or {}
    oversight = str(plan.get("oversight_status") or "pending")

    if ctx.get("dismissed"):
        return {"state": "DISMISSED", "reasons": [], "operator_ready": False,
                "display": "DISMISSED"}
    if ctx.get("fills_recorded"):
        return {"state": "IMPLEMENTATION_IN_PROGRESS", "reasons": [], "operator_ready": True,
                "display": "IMPLEMENTATION IN PROGRESS"}

    if not plan.get("legs"):
        reasons.append("no legs generated")
    if not ctx.get("settled"):
        reasons.append("settlement verification")
    if fin and fin.get("reconciles") is False:
        reasons.append(f"dollars do not reconcile (off by ${abs(fin.get('reconciliation_gap_usd') or 0):,.2f})")
    if not fin:
        reasons.append("financial reconciliation block missing")
    for w in (ctx.get("p0_warnings") or []):
        reasons.append(f"P0: {w}")
    if reasons:
        return {"state": "DATA_INCOMPLETE", "reasons": reasons, "operator_ready": False,
                "display": f"DATA INCOMPLETE — needs {', '.join(reasons)}"}

    stale = [l.get("ticker") for l in legs if l.get("price_stale")]
    if stale:
        return {"state": "QUOTES_STALE", "reasons": [f"stale quotes: {', '.join(stale)}"],
                "operator_ready": False,
                "display": f"QUOTES STALE — refresh {', '.join(stale)}"}

    analytics_missing = [k for k in ("pro_forma", "performance", "lookthrough", "entries")
                         if not (ctx.get("analytics_exist") or {}).get(k, True)]
    if analytics_missing or not ctx.get("memo_exists", True) or not ctx.get("audit_exists", True):
        miss = analytics_missing + ([] if ctx.get("memo_exists", True) else ["PM memo"]) \
            + ([] if ctx.get("audit_exists", True) else ["audit lineage"])
        return {"state": "DATA_INCOMPLETE", "reasons": miss, "operator_ready": False,
                "display": f"DATA INCOMPLETE — needs {', '.join(miss)}"}

    if oversight == "failed":
        return {"state": "OVERSIGHT_FAILED", "reasons": ["oversight verdict: failed"],
                "operator_ready": False, "display": "OVERSIGHT FAILED"}
    if ctx.get("is_major") and oversight not in ("passed", "pass"):
        return {"state": "OVERSIGHT_PENDING",
                "reasons": ["major event requires completed oversight"],
                "operator_ready": False,
                "display": "ANALYTICS READY — OVERSIGHT PENDING"}

    if ctx.get("locked"):
        return {"state": "OPERATOR_LOCKED", "reasons": [], "operator_ready": True,
                "display": "OPERATOR LOCKED"}
    if ctx.get("selected"):
        return {"state": "OPERATOR_SELECTED", "reasons": [], "operator_ready": True,
                "display": "OPERATOR SELECTED"}
    return {"state": "OPERATOR_READY", "reasons": [], "operator_ready": True,
            "display": "OPERATOR-READY"}


# ── decision scorecard (Phase 5) ─────────────────────────────────────────────
# Weights are visible, versioned, and operator-configurable via
# config/redeploy_decision_weights.yaml (same keys); they must sum to 1.0.

DEFAULT_WEIGHTS = {
    "sold_exposure_restoration": 0.20,
    "portfolio_improvement": 0.15,
    "diversification_overlap": 0.10,
    "risk_drawdown_suitability": 0.10,
    "income_quality": 0.10,
    "fees_efficiency": 0.10,
    "valuation_entry": 0.10,
    "regime_suitability": 0.05,
    "data_quality_evidence": 0.05,
    "account_suitability": 0.05,
}


def load_weights() -> dict[str, float]:
    try:
        import yaml
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent.parent / "config" / "redeploy_decision_weights.yaml"
        if p.is_file():
            raw = yaml.safe_load(p.read_text()) or {}
            w = {k: float(raw.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
            s = sum(w.values())
            if 0.99 <= s <= 1.01:
                return w
    except Exception:
        pass
    return dict(DEFAULT_WEIGHTS)


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def score_plan(plan: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Transparent per-dimension scores 0–100 with rationale; never one opaque number.

    ctx: {regime_posture, is_major, exposure_sectors: [...], account_type ('ira'|'taxable'),
          existing_income_overlay_usd}
    """
    legs = [l for l in (plan.get("legs") or []) if not l.get("is_reserve")]
    fin = plan.get("financials") or {}
    deployable = float(fin.get("deployable_cash_usd") or plan.get("net_proceeds_usd") or 0) or 1.0
    deployed = float(fin.get("executable_at_current_quote_usd") or plan.get("total_deployable_usd") or 0)
    reserve = float(fin.get("reserve_usd") or plan.get("reserve_usd") or 0)
    arch = plan.get("plan_archetype")
    risk_off = "off" in str(ctx.get("regime_posture") or "").lower() or \
               "defensive" in str(ctx.get("regime_posture") or "").lower()

    dims: dict[str, dict[str, Any]] = {}

    # 1. sold-exposure restoration — share of removed sectors addressed × deployment share
    sectors = ctx.get("exposure_sectors") or []
    restored = plan.get("restoration_summary") or {}
    if sectors and restored.get("restored_pct_of_removed") is not None:
        raw = _clamp(restored["restored_pct_of_removed"])
        note = f"restores {restored['restored_pct_of_removed']:.0f}% of removed sector dollars (deployed share included)"
    else:
        growth_syms = {"QQQ", "QQQM", "SCHG", "VUG", "SPY", "VOO", "VTI", "SWPPX", "FXAIX", "FZROX", "SWTSX"}
        capped_growth = {"JEPQ", "JEPI"}  # covered-call: counts half — upside participation is capped
        growth_d = sum(float(l.get("target_dollars") or 0) for l in legs if l.get("ticker") in growth_syms) \
            + 0.5 * sum(float(l.get("target_dollars") or 0) for l in legs if l.get("ticker") in capped_growth)
        raw = _clamp(growth_d / deployable * 100.0)
        note = f"growth-linked deployment {growth_d/deployable*100:.0f}% of deployable"
    if arch == "E":
        raw = min(raw, 15.0)
        note = "tactical gap plan — does NOT restore the sold mandate (by design)"
    if arch == "G":
        raw = 0.0
        note = "hold plan — restores nothing (by design)"
    dims["sold_exposure_restoration"] = {"raw": round(raw, 1), "note": note}

    # 2. portfolio improvement — income delta + fee delta vs sold
    inc = (plan.get("plan_income") or {}).get("expected_annual_income_usd")
    sold_inc = ctx.get("sold_annual_income_usd")
    if inc is not None and sold_inc is not None:
        delta = inc - sold_inc
        raw = _clamp(45.0 + delta / 250.0, 0.0, 85.0)
        note = f"income {'+' if delta >= 0 else ''}${delta:,.0f}/yr vs sold (income also scored separately — capped here to avoid double-counting)"
    elif inc is not None:
        raw = _clamp(40.0 + inc / 400.0, 0.0, 80.0)
        note = f"expected income ${inc:,.0f}/yr (sold income basis unavailable)"
    else:
        raw, note = 40.0, "income data unavailable — neutral-low score, not zero"
    dims["portfolio_improvement"] = {"raw": round(raw, 1), "note": note}

    # 3. diversification / overlap
    n = len(legs)
    overlap_pens = sum(1 for l in legs if l.get("overlap_note"))
    raw = _clamp(30.0 + n * 12.0 - overlap_pens * 15.0)
    dims["diversification_overlap"] = {
        "raw": round(raw, 1),
        "note": f"{n} legs, {overlap_pens} overlap flags"}

    # 4. risk / drawdown suitability — reserve share appropriateness given regime
    res_share = reserve / (deployable or 1.0)
    target_res = 0.5 if risk_off else 0.15
    # asymmetric: holding MORE reserve than target is mildly penalized in risk-off;
    # holding LESS is heavily penalized (deploying fully into a risk-off tape)
    over = max(0.0, res_share - target_res)
    under = max(0.0, target_res - res_share)
    raw = _clamp(100.0 - under * 160.0 - over * (60.0 if risk_off else 120.0))
    dims["risk_drawdown_suitability"] = {
        "raw": round(raw, 1),
        "note": f"reserve {res_share*100:.0f}% vs {target_res*100:.0f}% regime-appropriate target"}

    # 5. income quality — whole-plan yield
    wp_yield = (plan.get("plan_income") or {}).get("whole_plan_yield_pct")
    if wp_yield is None and inc is not None and deployable:
        wp_yield = inc / deployable * 100.0
    if wp_yield is not None:
        raw = _clamp(min(wp_yield, 6.0) * 14.0)
        note = (f"whole-plan yield {wp_yield:.2f}% (reserve included; scoring capped at 6% — "
                "high-yield vehicles trade upside for income)")
    else:
        raw, note = 35.0, "yield unavailable"
    dims["income_quality"] = {"raw": round(raw, 1), "note": note}

    # 6. fees / efficiency
    er = plan.get("weighted_expense_ratio_pct")
    if er is None:
        ers = [(l.get("expense_ratio_pct"), float(l.get("target_dollars") or 0)) for l in legs]
        num = sum((e or 0) * d for e, d in ers if e is not None)
        den = sum(d for e, d in ers if e is not None)
        er = round(num / den, 3) if den else None
    if er is not None:
        raw = _clamp(100.0 - er * 120.0)
        note = f"weighted ER {er:.3f}% on invested sleeve"
    else:
        raw, note = (90.0, "no fund fees (cash)") if arch == "G" else (50.0, "ER unavailable")
    dims["fees_efficiency"] = {"raw": round(raw, 1), "note": note}

    # 7. valuation / entry attractiveness — entry-package urgency
    urg = [str(l.get("urgency") or "") for l in legs]
    ready = sum(1 for u in urg if u == "ready")
    near = sum(1 for u in urg if u == "near_entry")
    raw = _clamp(40.0 + (ready * 30.0 + near * 15.0) / max(1, len(urg))) if urg else 50.0
    dims["valuation_entry"] = {
        "raw": round(raw, 1),
        "note": f"{ready} legs at entry, {near} near entry, of {len(urg)}"}

    # 8. regime suitability
    if risk_off:
        pref = {"F": 90.0, "G": 75.0, "D": 70.0, "C": 60.0, "A": 45.0, "B": 45.0, "E": 40.0}
        note = "risk-off regime favors staged/defensive deployment"
    else:
        pref = {"A": 85.0, "B": 80.0, "F": 65.0, "C": 60.0, "E": 55.0, "D": 40.0, "G": 25.0}
        note = "risk-on/neutral regime favors fuller strategic deployment"
    dims["regime_suitability"] = {"raw": pref.get(arch, 50.0), "note": note}

    # 9. data quality / evidence
    fresh = sum(1 for l in legs if not l.get("price_stale"))
    comp = sum(1 for l in legs if l.get("selection_evidence"))
    denom = max(1, len(legs))
    raw = _clamp(fresh / denom * 60.0 + comp / denom * 40.0) if legs else 70.0
    dims["data_quality_evidence"] = {
        "raw": round(raw, 1),
        "note": f"{fresh}/{denom} fresh quotes, {comp}/{denom} legs with candidate competition evidence"}

    # 10. account suitability — IRA: income/covered-call fine, wash-sale N/A
    acct_ira = "ira" in str(ctx.get("account_type") or plan.get("account_default") or "").lower()
    raw = 85.0 if acct_ira else 70.0
    note = "IRA — distributions tax-sheltered, no wash-sale constraint" if acct_ira \
        else "taxable — distribution tax drag applies"
    dims["account_suitability"] = {"raw": raw, "note": note}

    weights = ctx.get("weights") or load_weights()
    total = 0.0
    for k, d in dims.items():
        d["weight"] = weights[k]
        d["weighted"] = round(d["raw"] * weights[k], 2)
        total += d["weighted"]
    strongest = max(dims.items(), key=lambda kv: kv[1]["weighted"])
    weakest = min(dims.items(), key=lambda kv: kv[1]["weighted"])
    return {
        "decision_policy_version": DECISION_POLICY_VERSION,
        "dimensions": dims,
        "total_score": round(total, 1),
        "strongest_dimension": {"key": strongest[0], **strongest[1]},
        "weakest_dimension": {"key": weakest[0], **weakest[1]},
        "coverage_note": "each dimension carries its own data-coverage note; missing data scores neutral, never zero",
    }


# ── recommendation (Phases 5-6) ──────────────────────────────────────────────

_CHOOSE_WHEN = {
    "A": "the operator accepts immediate full equity timing risk to restore exposure now",
    "B": "reducing single-fund/manager concentration matters more than tracking the sold mandate closely",
    "C": "current income is more important than full upside participation",
    "D": "reducing portfolio beta/drawdown is the priority and the growth gap is accepted",
    "E": "the operator explicitly wants gap rotation INSTEAD of replacing the sold exposure",
    "F": "timing risk should be staged out (especially in a risk-off regime)",
    "G": "no deployment is wanted until conditions change; capital earns the reserve-vehicle yield",
}


def recommend(plans: list[dict[str, Any]], scores: dict[str, dict[str, Any]],
              ctx: dict[str, Any]) -> dict[str, Any]:
    """Plain-language recommendation: primary, ranked alternatives, do-not-choose."""
    ranked = sorted(
        [p for p in plans if p.get("plan_archetype") in scores],
        key=lambda p: -scores[p["plan_archetype"]]["total_score"])
    if not ranked:
        return {"ok": False, "error": "no scored plans"}

    # Concentration-cap violators are ineligible as primary (hard constraint, pre-scoring
    # policy — OVR-P1-CONCENTRATION); they remain visible with their violations stated.
    eligible = [p for p in ranked if not p.get("concentration_violations")]
    ineligible = [p for p in ranked if p.get("concentration_violations")]
    if not eligible:
        eligible = ranked
    primary = eligible[0]

    # Tie policy (frozen BEFORE generation; weights are never tuned to manufacture a
    # winner): a gap below DECISIVE_SCORE_GAP is NO DECISIVE WINNER. Documented
    # tie-breaker: in a risk-off regime prefer STAGED implementation when the staged
    # plan's destination is the quant leader (comparable destination quality).
    risk_off = "off" in str(ctx.get("regime_posture") or "").lower() or \
               "defensive" in str(ctx.get("regime_posture") or "").lower()
    top_gap = (scores[eligible[0]["plan_archetype"]]["total_score"]
               - scores[eligible[1]["plan_archetype"]]["total_score"]) if len(eligible) > 1 else 99.0
    decisive = top_gap >= DECISIVE_SCORE_GAP
    tie_note = None
    if not decisive:
        tie_note = (f"score gap {top_gap:.1f} < {DECISIVE_SCORE_GAP} — NO DECISIVE WINNER "
                    "on quant score alone")
        if risk_off:
            staged = next((p for p in eligible
                           if p.get("implementation_policy") == "staged"
                           and p.get("destination_archetype") == eligible[0]["plan_archetype"]),
                          None) or next((p for p in eligible
                                         if p.get("implementation_policy") == "staged"), None)
            if staged is not None:
                primary = staged
                tie_note += ("; tie-breaker applied: risk-off regime prefers STAGED "
                             f"implementation of the leading destination "
                             f"(Plan {staged.get('destination_archetype') or '—'})")
        else:
            tie_note += "; quant leader retained (no risk-off staging tie-breaker)"
    p_arch = primary["plan_archetype"]
    p_score = scores[p_arch]

    def _reasons(plan, sc):
        out = []
        for k, d in sorted(sc["dimensions"].items(), key=lambda kv: -kv[1]["weighted"])[:3]:
            out.append(f"{k.replace('_', ' ')}: {d['note']}")
        return out

    alternatives = []
    for p in ranked[1:3]:
        a = p["plan_archetype"]
        alternatives.append({
            "archetype": a, "objective": p.get("objective"),
            "total_score": scores[a]["total_score"],
            "choose_when": _CHOOSE_WHEN.get(a, "the stated objective matches operator intent"),
            "gap_to_primary": round(p_score["total_score"] - scores[a]["total_score"], 1),
        })

    do_not = []
    for p in ranked:
        a = p["plan_archetype"]
        if a == "E" and ctx.get("is_major"):
            do_not.append({
                "archetype": "E",
                "reason": "addresses portfolio gaps but does not replace the sold mandate — "
                          "never a substitute for the sold exposure on a major sale",
            })
        if str(p.get("oversight_status")) == "failed":
            do_not.append({"archetype": a, "reason": "oversight verdict: failed"})

    for p in ineligible:
        do_not.append({"archetype": p["plan_archetype"],
                       "reason": "concentration caps violated: "
                                 + "; ".join(p.get("concentration_violations") or [])})

    fin = primary.get("financials") or {}
    return {
        "decision_policy_version": DECISION_POLICY_VERSION,
        "decisive": decisive,
        "tie_policy": tie_note,
        "primary": {
            "archetype": p_arch,
            "destination_archetype": primary.get("destination_archetype") or p_arch,
            "implementation_policy": primary.get("implementation_policy") or "immediate",
            "objective": primary.get("objective"),
            "total_score": p_score["total_score"],
            "ultimate_target_usd": fin.get("executable_at_current_quote_usd"),
            "implement_now_usd": fin.get("implement_now_usd"),
            "pending_future_stages_usd": fin.get("pending_future_stages_usd"),
            "uncommitted_cash_usd": fin.get("uncommitted_cash_usd"),
            "deploy_now_usd": fin.get("executable_at_current_quote_usd"),  # legacy alias (= ultimate target)
            "reserve_usd": fin.get("reserve_usd"),
            "residual_usd": fin.get("whole_share_residual_usd"),
            "reasons": _reasons(primary, p_score),
            "strongest": p_score["strongest_dimension"]["note"],
            "weakest": p_score["weakest_dimension"]["note"],
        },
        "alternatives": alternatives,
        "do_not_choose": do_not,
        "scoreboard": {a: scores[a]["total_score"] for a in scores},
        "weights": {k: v for k, v in (ctx.get("weights") or load_weights()).items()},
    }


# ── PM memo (Phase 14) ───────────────────────────────────────────────────────

def build_pm_memo(event: dict[str, Any], primary: dict[str, Any],
                  recommendation: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Structured professional memo — sections of prose+numbers, never raw JSON in the UI."""
    fin = primary.get("financials") or {}
    inc = primary.get("plan_income") or {}
    legs = [l for l in (primary.get("legs") or []) if not l.get("is_reserve")]
    sold = str(event.get("symbol") or "").upper()
    net = float(fin.get("net_proceeds_usd") or event.get("proceeds_usd") or 0)
    regime = str(ctx.get("regime_posture") or "unknown")
    settled = bool(ctx.get("settled"))
    rec_p = recommendation.get("primary") or {}

    leg_lines = [
        f"{l['ticker']} — {l.get('role') or 'role unspecified'} — "
        f"${float(l.get('target_dollars') or 0):,.0f} ({l.get('target_shares') or 0} sh)"
        for l in legs]

    sections = {
        "executive_recommendation": (
            f"Given the {'verified' if settled else 'UNVERIFIED'} ${net:,.0f} proceeds, the current "
            f"{regime} regime and existing portfolio overlap, the system leans toward "
            f"Plan {rec_p.get('archetype')} — {primary.get('objective')}. It deploys "
            f"${float(rec_p.get('deploy_now_usd') or 0):,.0f} now, retains "
            f"${float(rec_p.get('reserve_usd') or 0):,.0f} in reserve "
            f"(+${float(rec_p.get('residual_usd') or 0):,.2f} whole-share residual)."),
        "sale_summary": (
            f"Sold {sold} in {event.get('account')} on {event.get('sold_at')}; net proceeds "
            f"${net:,.0f}; settlement {'verified' if settled else 'not yet verified'}."),
        "exposure_removed": ctx.get("exposure_removed_text")
            or "See EVENT ANALYSIS for the full sector/holding decomposition.",
        "portfolio_context": ctx.get("portfolio_context_text")
            or f"Regime: {regime}. See portfolio gaps in EVENT ANALYSIS.",
        "regime_context": f"Current regime: {regime}.",
        "alternatives_considered": [
            f"Plan {a['archetype']} (score {a['total_score']}): choose when {a['choose_when']}"
            for a in recommendation.get("alternatives") or []],
        "recommended_allocation": leg_lines,
        "reserve": (
            f"${float(fin.get('reserve_usd') or 0):,.0f} reserve"
            + (f" in {primary.get('reserve_vehicle')}" if primary.get("reserve_vehicle") else "")
            + f"; whole-share residual ${float(fin.get('whole_share_residual_usd') or 0):,.2f}"),
        "entry_stages": ctx.get("entry_stages_text")
            or "Staged entries per leg are in ENTRY PLAN with triggers.",
        "expected_impact": (
            f"Expected income ${float(inc.get('expected_annual_income_usd') or 0):,.0f}/yr; "
            f"whole-plan yield {inc.get('whole_plan_yield_pct', '—')}%; "
            f"invested-sleeve yield {inc.get('invested_sleeve_yield_pct', '—')}%."),
        "income_and_fees": ctx.get("income_fee_text")
            or "Income model and weighted fees per tab carry the same calculation snapshot.",
        "risk_analysis": "; ".join(primary.get("risks") or []) or "See scenario matrix.",
        "remaining_gaps": "; ".join(
            f"{s.get('sector')}: ${float(s.get('usd_removed') or 0):,.0f} not restored"
            for s in (primary.get("unmet_exposure") or {}).get("sectors_not_restored") or []) or "none identified",
        "change_conditions": primary.get("tranche_triggers") or [
            "regime shifts out of risk-off (accelerate deployment)",
            "primary leg breaches its do-not-chase price (re-plan entries)",
            "portfolio gap changes materially (re-run recompute)"],
        "next_operator_action": (
            "Review PLAN COMPARISON, run oversight if pending, then approve the plan for "
            "operator implementation review. This desk places no orders."),
        "sources_and_timestamps": ctx.get("sources_text")
            or "All figures carry per-leg quote timestamps; see calculation_as_of on each tab.",
        "oversight_conclusion": f"Oversight status: {primary.get('oversight_status')}.",
        "advisory_statement": "Advisory only — no broker execution from this desk.",
    }
    return {"memo_version": DECISION_POLICY_VERSION, "sections": sections}
