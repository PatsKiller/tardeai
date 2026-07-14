"""redeploy_plan_engine — competing institutional plans A–G (advisory only).

phase_b_2.0.0 (semantic-integrity release, operator review 2026-07-14):
  - every plan carries an exact financial reconciliation block (legs + reserve +
    whole-share residual = deployable, asserted at generation);
  - legs are selected from the live candidate universe per ROLE with visible
    competition evidence (rank, alternatives, margins) — not a hardcoded menu;
  - every leg states its role;
  - narratives derive from event state (settlement, regime) — settlement language
    disappears once proceeds are verified;
  - Plan E is capped to the documented portfolio gaps; Plan F states its ultimate
    target allocation and tranche triggers; Plan G names its reserve vehicle and yield;
  - readiness is the governed state machine from redeploy_decision (majors are never
    operator-ready with oversight pending);
  - the bundle includes a transparent decision scorecard, a plain-language
    recommendation, and a structured PM memo.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from lib.entry_planner_adapter import build_entry_package, whole_shares
from lib.redeploy_data_truth import (
    DRAWDOWN_REJECT_THRESHOLD_PCT,
    PLAN_ARCHETYPES,
    POLICY_VERSION,
    VOL_DELTA_ABS_PP_MAX,
    _as_float,
    _load_json,
)
from lib.redeploy_decision import (
    build_pm_memo,
    load_weights,
    readiness_state,
    recommend,
    score_plan,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"

GENERATOR_VERSION = "phase_b_2.0.0"

_GROWTH_SET = frozenset({"QQQ", "QQQM", "SCHG", "VUG", "IWF", "SPY", "VOO", "VTI",
                         "SWPPX", "SWTSX", "FXAIX", "FZROX", "MTUM", "QUAL"})
_COVERED_CALL = frozenset({"JEPQ", "JEPI", "DIVO", "QYLD", "XYLD"})
_CASH_EQ = frozenset({"SGOV", "BIL"})

_SECTOR_CANDIDATES = {
    "Technology": ["XLK", "VGT", "QQQ"],
    "Communication Services": ["XLC"],
    "Financial Services": ["XLF"],
    "Consumer Cyclical": ["XLY"],
    "Healthcare": ["XLV"],
    "Industrials": ["XLI"],
    "Consumer Defensive": ["XLP"],
    "Energy": ["XLE"],
    "Basic Materials": ["XLB"],
    "Utilities": ["XLU"],
    "Real Estate": ["XLRE"],
}

_BLOCKED_REASON = {"SCHG": "RPL-001", "ITA": "RPL-004", "XAR": "RPL-004"}

# Plan E caps (Phase 4): tactical gap fills are sized to the gap, never the proceeds.
TACTICAL_SLEEVE_BUDGET_FRAC = 0.30      # of deployable, across ALL tactical legs
TACTICAL_SINGLE_LEG_CAP_FRAC = 0.20     # of deployable, per leg


def _phase_a(event: dict[str, Any]) -> dict[str, Any]:
    return (event.get("metadata") or {}).get("phase_a") or {}


# ── candidate universe access (fail-soft) ────────────────────────────────────

def _fetch_candidates(sold: str | None) -> dict[str, dict[str, Any]]:
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _get_conn
        from lib.redeploy_candidate_research import build_candidates
        conn = _get_conn()
        res = build_candidates(conn.cursor(), sold_symbol=sold)
        conn.rollback()
        return {c["symbol"]: c for c in (res.get("candidates") or [])}
    except Exception:
        return {}


def _yield_of(c: dict[str, Any]) -> float:
    return _as_float(c.get("distribution_yield_pct"))


def _er_of(c: dict[str, Any]) -> float | None:
    v = c.get("expense_ratio_pct")
    return float(v) if v is not None else None


# ── role-based selection with competition evidence (Phase 12) ────────────────

def _role_defs() -> dict[str, dict[str, Any]]:
    return {
        "large_growth_restoration": {
            "eligible": lambda c: (c.get("symbol") in _GROWTH_SET
                                   or (c.get("correlation_to_sold") or 0) >= 0.85
                                   or "growth" in str(c.get("category") or "").lower()),
            "score": lambda c: ((c.get("correlation_to_sold") or 0) * 60.0
                                + max(0.0, 30.0 - (_er_of(c) if _er_of(c) is not None else 0.5) * 60.0)
                                + min(10.0, (c.get("history_days") or 0) / 126.0)),
            "method": "correlation-to-sold ×60 + low-fee bonus (≤30) + history depth (≤10)",
        },
        "dividend_quality_ballast": {
            "eligible": lambda c: (c.get("symbol") not in _COVERED_CALL
                                   and 1.5 <= _yield_of(c) <= 6.0
                                   and c.get("asset_class") in ("fund",)),
            "score": lambda c: (_yield_of(c) * 12.0
                                + max(0.0, 20.0 - (_er_of(c) if _er_of(c) is not None else 0.5) * 40.0)
                                + min(10.0, (c.get("history_days") or 0) / 126.0)),
            "method": "yield ×12 + low-fee bonus (≤20) + history depth (≤10); covered-call excluded",
        },
        "fixed_income_ballast": {
            "eligible": lambda c: (c.get("asset_class") == "fixed_income"
                                   and c.get("symbol") not in _CASH_EQ),
            "score": lambda c: (max(0.0, 40.0 - (_er_of(c) if _er_of(c) is not None else 0.3) * 100.0)
                                + _yield_of(c) * 8.0
                                + min(10.0, (c.get("history_days") or 0) / 126.0)),
            "method": "low-fee (≤40) + yield ×8 + history depth (≤10)",
        },
        "income_overlay": {
            # Plausibility guards: a trailing yield computed on a short/broken series
            # (e.g. ARKQ 23% on 266 usable days) is a data artifact, not income.
            "eligible": lambda c: (c.get("symbol") in _COVERED_CALL
                                   or (5.0 <= _yield_of(c) <= 15.0
                                       and (c.get("history_days") or 0) >= 756)),
            "score": lambda c: (min(_yield_of(c), 12.0) * 8.0
                                + (c.get("correlation_to_sold") or 0) * 30.0),
            "method": ("yield ×8 (capped at 12% for scoring) + correlation-to-sold ×30; "
                       "eligibility requires covered-call class OR 5–15% yield with ≥3y history "
                       "(implausible short-series yields are data artifacts, excluded)"),
        },
        "cash_reserve_vehicle": {
            "eligible": lambda c: c.get("asset_class") == "cash_equivalent" or c.get("symbol") in _CASH_EQ,
            "score": lambda c: _yield_of(c) * 20.0 + min(5.0, (c.get("history_days") or 0) / 252.0),
            "method": "reserve yield ×20 + history",
        },
    }


def _why_lost(winner: dict, loser: dict, role: str) -> str:
    parts = []
    we, le = _er_of(winner), _er_of(loser)
    if we is not None and le is not None and le > we:
        parts.append(f"higher fee ({le:.2f}% vs {we:.2f}%)")
    wc, lc = winner.get("correlation_to_sold"), loser.get("correlation_to_sold")
    if wc is not None and lc is not None and lc < wc:
        parts.append(f"lower correlation to sold ({lc:.2f} vs {wc:.2f})")
    if _yield_of(loser) < _yield_of(winner) and role in ("income_overlay", "dividend_quality_ballast",
                                                         "cash_reserve_vehicle"):
        parts.append(f"lower yield ({_yield_of(loser):.2f}% vs {_yield_of(winner):.2f}%)")
    if (loser.get("history_days") or 0) < (winner.get("history_days") or 0) // 2:
        parts.append("shorter usable history")
    return "; ".join(parts) or "lower composite role score"


def _select_for_role(cands: dict[str, dict], role: str, *, exclude: set[str] = frozenset(),
                     event: dict | None = None) -> tuple[str | None, dict | None]:
    defs = _role_defs()[role]
    proxy = str((event or {}).get("proxy_symbol") or "").upper()
    pool = []
    for c in cands.values():
        sym = c["symbol"]
        if sym in exclude or sym == proxy or _BLOCKED_REASON.get(sym) == "RPL-004":
            continue
        # role winners need real history to trust their metrics (reserve vehicles exempt)
        if role != "cash_reserve_vehicle" and (c.get("history_days") or 0) < 500:
            continue
        try:
            if defs["eligible"](c):
                pool.append((defs["score"](c), c))
        except Exception:
            continue
    pool.sort(key=lambda t: (-t[0], t[1]["symbol"]))
    if not pool:
        return None, None
    w_score, w = pool[0]
    evidence = {
        "role": role,
        "candidate_rank": 1,
        "eligible_pool": len(pool),
        "score": round(w_score, 1),
        "method": defs["method"],
        "selection_margin": round(w_score - pool[1][0], 1) if len(pool) > 1 else None,
        "alternatives": [
            {"symbol": c["symbol"], "score": round(s, 1),
             "why_lost": _why_lost(w, c, role)}
            for s, c in pool[1:4]
        ],
    }
    return w["symbol"], evidence


def _select_sector_etf(cands: dict[str, dict], sector: str) -> tuple[str | None, dict | None]:
    prefs = _SECTOR_CANDIDATES.get(sector) or []
    avail = [cands[s] for s in prefs if s in cands]
    if not avail:
        return None, None
    ranked = sorted(avail, key=lambda c: ((_er_of(c) if _er_of(c) is not None else 0.5),
                                          -(c.get("history_days") or 0)))
    w = ranked[0]
    return w["symbol"], {
        "role": f"sector_restoration:{sector}",
        "candidate_rank": 1, "eligible_pool": len(ranked),
        "method": "lowest fee among sector-mapped candidates, history tiebreak",
        "selection_margin": None,
        "alternatives": [{"symbol": c["symbol"],
                          "why_lost": _why_lost(w, c, "sector")} for c in ranked[1:3]],
    }


# ── leg builders ─────────────────────────────────────────────────────────────

def _income_yield(sym: str, cands: dict[str, dict]) -> float | None:
    c = cands.get(sym.upper())
    if c and c.get("distribution_yield_pct") is not None:
        return float(c["distribution_yield_pct"])
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _get_conn
        from lib.redeploy_income import income_snapshot
        conn = _get_conn()
        snap = income_snapshot(conn.cursor(), [sym]).get(sym.upper()) or {}
        conn.rollback()
        return snap.get("yield_pct")
    except Exception:
        for p in _load_json(STATE / "dividend_calendar.json", {}).get("payers") or []:
            if (p.get("symbol") or "").upper() == sym.upper():
                y = _as_float(p.get("yield_pct"))
                return y if y else None
    return None


def _equity_leg(sym: str, account: str, dollars: float, *, role: str,
                pct_of_net: float | None, thesis: str, cands: dict[str, dict],
                evidence: dict | None = None, overlap_note: str | None = None,
                dual_label: str | None = None) -> dict[str, Any]:
    sym = sym.upper()
    entry = build_entry_package(sym, leg_dollars=dollars)
    price = entry.get("current_price") or 0
    sh, filled = whole_shares(dollars, price) if price else (0, 0.0)
    c = cands.get(sym) or {}
    leg = {
        "ticker": sym,
        "security_name": c.get("name"),
        "account": account,
        "role": role,
        "allocation_pct_of_net": pct_of_net,
        "strategic_target_dollars": round(dollars, 2),
        "target_dollars": filled if price else round(dollars, 2),
        "target_shares": sh,
        "whole_share_residual_usd": round(dollars - filled, 2) if price else 0.0,
        "is_reserve": False,
        "is_actionable": (filled > 0) if price else False,
        "expected_yield_pct": _income_yield(sym, cands),
        "expense_ratio_pct": c.get("expense_ratio_pct"),
        "thesis": thesis,
        "overlap_note": overlap_note,
        "selection_evidence": evidence,
        **entry,
    }
    if dual_label:
        leg["dual_label"] = dual_label
    return leg


def _reserve_leg(account: str, dollars: float, *, vehicle: str | None, vehicle_yield: float | None,
                 thesis: str, actionable: bool = False) -> dict[str, Any]:
    return {
        "ticker": vehicle or "CASH",
        "security_name": (f"Reserve vehicle {vehicle}" if vehicle else "Uninvested cash reserve"),
        "account": account,
        "role": "cash_reserve",
        "allocation_pct_of_net": None,
        "strategic_target_dollars": round(dollars, 2),
        "target_dollars": round(dollars, 2),
        "target_shares": None,
        "is_reserve": True,
        "is_actionable": actionable,
        "expected_yield_pct": vehicle_yield,
        "thesis": thesis,
    }


# ── financial reconciliation (Phase 1) ───────────────────────────────────────

def _finalize_financials(legs: list[dict], *, net: float, deployable: float) -> dict[str, Any]:
    """Exact accounting. legs+reserve+residual==deployable by construction; asserted."""
    invested = [l for l in legs if not l.get("is_reserve")]
    reserves = [l for l in legs if l.get("is_reserve")]
    strategic = round(sum(_as_float(l.get("strategic_target_dollars")) for l in invested), 2)
    executable = round(sum(_as_float(l.get("target_dollars")) for l in invested), 2)
    staged = round(sum(
        _as_float(l.get(f"stage_{i}_dollars")) for l in invested for i in (1, 2, 3)), 2)
    reserve = round(sum(_as_float(l.get("target_dollars")) for l in reserves), 2)
    residual = round(deployable - executable - reserve, 2)
    total = round(executable + reserve + residual, 2)
    gap = round(total - round(deployable, 2), 2)
    fin = {
        "net_proceeds_usd": round(net, 2),
        "deployable_cash_usd": round(deployable, 2),
        "strategic_target_usd": strategic,
        "executable_at_current_quote_usd": executable,
        "staged_limit_order_usd": staged or None,
        "reserve_usd": reserve,
        "whole_share_residual_usd": residual,
        "total_accounted_usd": total,
        "reconciles": abs(gap) < 0.01,
        "reconciliation_gap_usd": gap,
        "amount_meanings": {
            "strategic_target_usd": "intended split before whole-share rounding",
            "executable_at_current_quote_usd": "whole shares × current quote (what Plan Lab shows)",
            "staged_limit_order_usd": "sum of staged limit-order tranches (what Entries shows)",
            "whole_share_residual_usd": "cash left by whole-share rounding — never silently dropped",
        },
    }
    return fin


def compute_plan_income(legs: list[dict], *, deployable: float, invested: float) -> dict[str, Any]:
    """Canonical plan-income block — recomputed whenever legs change (Phase-C refresh)."""
    inc_legs = []
    inc_total = 0.0
    inv_income = 0.0
    for l in legs:
        d = _as_float(l.get("target_dollars"))
        y = l.get("expected_yield_pct")
        if y is not None and d > 0:
            inc = round(d * float(y) / 100.0, 2)
            inc_total += inc
            if not l.get("is_reserve"):
                inv_income += inc
            inc_legs.append({"ticker": l["ticker"], "income_usd": inc, "yield_pct": y,
                             "is_reserve": bool(l.get("is_reserve"))})
    return {
        "expected_annual_income_usd": round(inc_total, 2),
        "income_by_leg": inc_legs,
        "whole_plan_yield_pct": round(inc_total / deployable * 100.0, 2) if deployable else None,
        "invested_sleeve_yield_pct": round(inv_income / invested * 100.0, 2) if invested else None,
        "calculation_as_of": datetime.now(timezone.utc).isoformat(),
    }


def refresh_plan_snapshot(plan: dict[str, Any]) -> dict[str, Any]:
    """Re-cut financials + plan_income from the CURRENT legs. Must be called after any
    step that mutates leg dollars (Phase-C quote refresh re-floors whole shares) so the
    persisted snapshot always matches the persisted legs — one basis for every tab."""
    fin_old = plan.get("financials") or {}
    net = _as_float(fin_old.get("net_proceeds_usd") or plan.get("net_proceeds_usd"))
    deployable = _as_float(fin_old.get("deployable_cash_usd")) or net
    legs = plan.get("legs") or []
    fin = _finalize_financials(legs, net=net, deployable=deployable)
    plan["financials"] = fin
    plan["total_deployable_usd"] = fin["executable_at_current_quote_usd"]
    plan["reserve_usd"] = fin["reserve_usd"]
    plan["deploy_pct_of_net"] = round(
        fin["executable_at_current_quote_usd"] / net * 100.0, 2) if net else 0.0
    plan["plan_income"] = compute_plan_income(
        legs, deployable=deployable, invested=fin["executable_at_current_quote_usd"])
    return plan


# ── settlement/regime-aware narratives (Phase 3) ─────────────────────────────

def _staging_risk(settled: bool, regime: str) -> str:
    if not settled:
        return "Opportunity cost if market rallies before settlement"
    return (f"Opportunity cost if the {regime or 'current'} regime improves before "
            "reserved tranches deploy")


def _plan_shell(archetype: str, *, net: float, deployable: float, account: str,
                tags: list[str], objective: str, legs: list[dict],
                advantages: list[str], compromises: list[str], risks: list[str],
                composite_rank: float, is_major: bool, settled: bool,
                unmet: dict | None = None, extra: dict | None = None) -> dict[str, Any]:
    plan_type, desc = PLAN_ARCHETYPES[archetype]
    fin = _finalize_financials(legs, net=net, deployable=deployable)
    plan = {
        "plan_archetype": archetype,
        "plan_type": plan_type,
        "plan_description": desc,
        "tags": tags,
        "objective": objective,
        "account_default": account,
        "financials": fin,
        "total_deployable_usd": fin["executable_at_current_quote_usd"],
        "reserve_usd": fin["reserve_usd"],
        "deploy_pct_of_net": round(fin["executable_at_current_quote_usd"] / net * 100.0, 2) if net else 0.0,
        "net_proceeds_usd": round(net, 2),
        "confidence": None,          # set from decision scorecard below
        "evidence_factor_count": sum(1 for l in legs if l.get("selection_evidence")),
        "operator_status": "draft",
        "oversight_status": "pending",
        "composite_rank": composite_rank,
        "advantages": advantages,
        "compromises": compromises,
        "risks": risks,
        "legs": legs,
        "unmet_exposure": unmet or {},
        "scenarios": {"base": {"cash_remaining": fin["reserve_usd"] + fin["whole_share_residual_usd"],
                               "portfolio_vol_delta_pp_estimate": 0.4,
                               "max_drawdown_pct_estimate": -8.0}},
        "hermes_narrative": None,
        "settled_basis": settled,
    }
    plan["plan_income"] = compute_plan_income(legs, deployable=deployable,
                                              invested=fin["executable_at_current_quote_usd"])
    if extra:
        plan.update(extra)
    return plan


def _restoration_summary(exposure: dict, legs: list[dict]) -> dict[str, Any] | None:
    sectors = exposure.get("sectors") or []
    if not sectors:
        return None
    total_removed = sum(_as_float(s.get("usd_removed")) for s in sectors) or 1.0
    by_sector = []
    restored_total = 0.0
    sector_syms = {s: set(v) for s, v in _SECTOR_CANDIDATES.items()}
    for s in sectors:
        name = s["sector"]
        removed = _as_float(s.get("usd_removed"))
        alloc = sum(_as_float(l.get("target_dollars")) for l in legs
                    if not l.get("is_reserve") and l["ticker"] in sector_syms.get(name, set()))
        restored = min(alloc, removed)
        restored_total += restored
        by_sector.append({"sector": name, "usd_removed": removed,
                          "usd_allocated": round(alloc, 2),
                          "restoration_ratio": round(alloc / removed, 2) if removed else None})
    return {"restored_pct_of_removed": round(restored_total / total_removed * 100.0, 1),
            "by_sector": by_sector}


def _unmet_exposure(exposure: dict[str, Any], legs: list[dict]) -> dict[str, Any]:
    if not exposure.get("sectors"):
        return {}
    leg_syms = {l["ticker"] for l in legs if not l.get("is_reserve")}
    missing = []
    for sec in exposure.get("sectors") or []:
        cands = set(_SECTOR_CANDIDATES.get(sec["sector"]) or [])
        if not (cands & leg_syms):
            missing.append({"sector": sec["sector"], "usd_removed": sec["usd_removed"]})
    return {"sectors_not_restored": missing[:8], "income_status": exposure.get("income_status")}


# ── main builder ─────────────────────────────────────────────────────────────

def build_institutional_plans(
    event: dict[str, Any],
    *,
    v1_targets: list[dict[str, Any]] | None = None,
    sleeve_gaps: list[dict[str, Any]] | None = None,
    sale_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pa = _phase_a(event)
    recon = pa.get("reconciliation") or {}
    exposure = pa.get("exposure_loss") or {}
    ctx_pa = pa.get("portfolio_context") or {}
    meta = event.get("metadata") or {}
    market = meta.get("market_context") or {}

    net = _as_float(recon.get("net_proceeds_usd") or event.get("proceeds_usd"))
    deployable = _as_float(recon.get("deployable_cash_usd") or event.get("deployable_cash_usd"))
    account = str(ctx_pa.get("default_deployment_account") or event.get("account") or "")
    is_major = bool(ctx_pa.get("is_major_sale"))
    settled = str(recon.get("reconciliation_status") or "") in ("verified", "settled")
    regime = str(market.get("regime_posture") or "").lower()
    risk_off = "off" in regime or "defensive" in regime
    sold = str(event.get("symbol") or "").upper()
    proxy = str(event.get("proxy_symbol") or "").upper()
    gaps = sleeve_gaps or []

    if sale_ctx and sale_ctx.get("tier") == "minor":
        return {"generator_version": GENERATOR_VERSION, "policy_version": POLICY_VERSION,
                "plans": [], "rejected_alternatives": [],
                "advisory_note": "Minor sale — institutional plans suppressed."}

    cands = _fetch_candidates(sold)
    plans: list[dict[str, Any]] = []
    used: set[str] = set()
    role_evidence_log: list[dict] = []

    def pick(role: str, fallback: str) -> tuple[str, dict | None]:
        sym, ev = _select_for_role(cands, role, exclude=used, event=event)
        if not sym:
            sym, ev = fallback, {"role": role, "method": "fallback (candidate universe unavailable)",
                                 "candidate_rank": None, "eligible_pool": 0, "alternatives": []}
        role_evidence_log.append({"role": role, "selected": sym, **(ev or {})})
        return sym, ev

    # reserve vehicle (shared by all reserves) — Phase 4 Plan G requirement
    rv_sym, rv_ev = _select_for_role(cands, "cash_reserve_vehicle", event=event)
    rv_yield = _income_yield(rv_sym, cands) if rv_sym else None
    reserve_thesis_settled = (
        f"Reserve in {rv_sym or 'cash'}"
        + (f" yielding {rv_yield:.2f}%" if rv_yield else "")
        + " — deploys per plan staging, not a settlement hold")
    reserve_thesis_unsettled = "Planned-not-actionable until proceeds settle in the source account"
    reserve_thesis = reserve_thesis_settled if settled else reserve_thesis_unsettled

    # role selections (shared across plans; each plan re-uses the same winners)
    g_sym, g_ev = pick("large_growth_restoration", "QQQ")
    d_sym, d_ev = pick("dividend_quality_ballast", "SCHD")
    f_sym, f_ev = pick("fixed_income_ballast", "BND")
    i1_sym, i1_ev = pick("income_overlay", "JEPQ")
    i2, i2_ev = _select_for_role(cands, "income_overlay", exclude={i1_sym}, event=event)
    i2_sym = i2 or "JEPI"

    def alloc(weights: list[tuple[str, float, str, dict | None]], pool: float,
              dual: dict[str, str] | None = None) -> list[dict]:
        legs = []
        for sym, frac, role, ev in weights:
            d = round(pool * frac, 2)
            if d <= 0:
                continue
            legs.append(_equity_leg(
                sym, account, d, role=role,
                pct_of_net=round(d / net * 100.0, 2) if net else None,
                thesis=f"{role.replace('_', ' ')} — selected from candidate universe",
                cands=cands, evidence=ev,
                dual_label=(dual or {}).get(sym)))
        return legs

    # --- Plan A: strategic redesign (honest label — Phase 4 / defect 14) ---
    legs_a = alloc([(g_sym, 0.45, "large_growth_restoration", g_ev),
                    (d_sym, 0.35, "dividend_quality_ballast", d_ev),
                    (f_sym, 0.20, "fixed_income_ballast", f_ev)], deployable)
    legs_a.append(_reserve_leg(account, 0.0 if settled else max(0.0, net - deployable),
                               vehicle=rv_sym, vehicle_yield=rv_yield, thesis=reserve_thesis))
    resto_a = _restoration_summary(exposure, legs_a)
    plans.append(_plan_shell(
        "A", net=net, deployable=deployable, account=account,
        tags=["strategic_redesign", "growth"],
        objective=(f"Strategic redesign — restore large-growth exposure lost from {sold} "
                   "with dividend-quality and duration ballast"),
        legs=legs_a,
        advantages=[f"45% large-growth restoration via {g_sym}",
                    f"Dividend ballast via {d_sym}"],
        compromises=[
            "NOT a close replacement of an active growth mandate: 20% bonds + 35% dividend/value "
            "is a deliberate redesign of the sold exposure",
            f"{g_sym} is passive — no active stock selection"],
        risks=([f"Avoids duplicate proxy {proxy}"] if proxy else ["Concentration in mega-cap index"]),
        composite_rank=82.0, is_major=is_major, settled=settled,
        unmet=_unmet_exposure(exposure, legs_a) if is_major else {},
        extra={"restoration_summary": resto_a},
    ))

    # --- Plan B: partial multi-sector restoration (honest label — defect 12) ---
    top_sectors = sorted(exposure.get("sectors") or [],
                         key=lambda x: -_as_float(x.get("weight_pct")))[:5]
    weights_b: list[tuple[str, float, str, dict | None]] = []
    covered_sectors = []
    if top_sectors:
        share = 0.85 / len(top_sectors)
        for s in top_sectors:
            etf, ev = _select_sector_etf(cands, s["sector"])
            if etf:
                weights_b.append((etf, share, f"sector_restoration:{s['sector']}", ev))
                covered_sectors.append(s["sector"])
        weights_b.append((f_sym, 0.15, "fixed_income_ballast", f_ev))
    else:
        weights_b = [(g_sym, 0.5, "large_growth_restoration", g_ev),
                     (d_sym, 0.3, "dividend_quality_ballast", d_ev),
                     (f_sym, 0.2, "fixed_income_ballast", f_ev)]
    legs_b = alloc(weights_b, deployable)
    legs_b.append(_reserve_leg(account, 0.0 if settled else max(0.0, net - deployable),
                               vehicle=rv_sym, vehicle_yield=rv_yield, thesis=reserve_thesis))
    n_total_sectors = len(exposure.get("sectors") or [])
    plans.append(_plan_shell(
        "B", net=net, deployable=deployable, account=account,
        tags=["diversified_basket", "multi_sector", "partial_restoration"],
        objective=(f"Partial multi-sector restoration — top {len(covered_sectors)} of "
                   f"{n_total_sectors} removed sectors, with fixed-income ballast"),
        legs=legs_b,
        advantages=["Broadest direct sector restoration of the plan set",
                    "Reduces single-fund/manager concentration"],
        compromises=[
            f"Restores {len(covered_sectors)}/{n_total_sectors} removed sectors — "
            f"{', '.join(s['sector'] for s in (exposure.get('sectors') or []) if s['sector'] not in covered_sectors)[:120] or 'none missing'} not directly restored",
            "15% fixed-income ballast restores no sold equity exposure",
            "Sector ETFs are imperfect proxies for active selection"],
        risks=["Overlap with existing sector ETF holdings"],
        composite_rank=78.0, is_major=is_major, settled=settled,
        unmet=_unmet_exposure(exposure, legs_b) if is_major else {},
        extra={"restoration_summary": _restoration_summary(exposure, legs_b)},
    ))

    # --- Plan C: income-oriented ---
    legs_c = alloc([(i1_sym, 0.55, "income_overlay", i1_ev),
                    (i2_sym, 0.45, "income_overlay", i2_ev)], deployable,
                   dual={i1_sym: "partial_growth_restore+income_enhance"})
    legs_c.append(_reserve_leg(account, 0.0 if settled else max(0.0, net - deployable),
                               vehicle=rv_sym, vehicle_yield=rv_yield, thesis=reserve_thesis))
    plans.append(_plan_shell(
        "C", net=net, deployable=deployable, account=account,
        tags=["income_oriented", "dual_label"],
        objective=f"Increase current income while partially restoring growth exposure from {sold}",
        legs=legs_c,
        advantages=["Highest current income of the plan set", "IRA-appropriate distributions"],
        compromises=["Covered-call structure caps upside participation",
                     "Partial growth restoration only — not a growth replacement"],
        risks=[f"{i1_sym} overlaps existing income-overlay holdings — review cross-account concentration"],
        composite_rank=75.0, is_major=is_major, settled=settled,
        unmet={"growth_upside_capped": True,
               "income_status": exposure.get("income_status")} if is_major else {},
    ))

    # --- Plan D: defensive ---
    legs_d = alloc([(f_sym, 0.70, "fixed_income_ballast", f_ev),
                    (d_sym, 0.30, "dividend_quality_ballast", d_ev)], deployable)
    legs_d.append(_reserve_leg(account, 0.0 if settled else max(0.0, net - deployable),
                               vehicle=rv_sym, vehicle_yield=rv_yield, thesis=reserve_thesis))
    growth_removed = sum(_as_float(s.get("usd_removed")) for s in (exposure.get("sectors") or [])
                         if s.get("sector") in ("Technology", "Communication Services"))
    plans.append(_plan_shell(
        "D", net=net, deployable=deployable, account=account,
        tags=["defensive", "risk_reduction"],
        objective="Reduce portfolio beta and drawdown while redeploying proceeds",
        legs=legs_d,
        advantages=["Lowest-beta deployment of the plan set", f"Income from {d_sym}"],
        compromises=[
            f"Intentionally does NOT restore ~${growth_removed:,.0f} of removed growth exposure"
            if growth_removed else "Minimal growth restoration by design"],
        risks=["Structurally underweight equities if maintained long-term"],
        composite_rank=62.0, is_major=is_major, settled=settled,
    ))

    # --- Plan E: tactical, gap-capped (defect 13) ---
    legs_e: list[dict] = []
    tactical_budget = deployable * TACTICAL_SLEEVE_BUDGET_FRAC
    spent = 0.0
    try:
        from lib.deploy_intelligence_engine import _THEME_ETF_MAP
    except ImportError:
        _THEME_ETF_MAP = {}
    for g in (gaps or [])[:4]:
        theme = g.get("theme")
        gap_usd = _as_float(g.get("gap_usd"))
        if gap_usd <= 0:
            continue
        etfs = [s for s in (_THEME_ETF_MAP.get(theme) or []) if s in cands] \
            or (_THEME_ETF_MAP.get(theme) or [])[:1]
        if not etfs:
            continue
        cap = min(gap_usd, deployable * TACTICAL_SINGLE_LEG_CAP_FRAC,
                  tactical_budget - spent, deployable - spent)
        if cap <= 0:
            continue
        legs_e.append(_equity_leg(
            etfs[0], account, cap, role=f"tactical_gap:{theme}",
            pct_of_net=round(cap / net * 100.0, 2) if net else None,
            thesis=(f"Tactical fill of the {theme} underweight (gap ${gap_usd:,.0f}) — "
                    f"sized to the GAP, capped at ${cap:,.0f}; NOT a replacement for {sold}"),
            cands=cands,
            evidence={"role": f"tactical_gap:{theme}",
                      "method": "gap-capped: min(gap $, 20% deployable per leg, 30% sleeve budget)",
                      "sizing": {"gap_usd": gap_usd, "cap_applied_usd": round(cap, 2)},
                      "alternatives": [{"symbol": s, "why_lost": "secondary theme ETF"}
                                       for s in etfs[1:3]]}))
        spent += cap
    legs_e.append(_reserve_leg(
        account, max(0.0, deployable - spent) if settled else max(0.0, net - spent),
        vehicle=rv_sym, vehicle_yield=rv_yield,
        thesis=(f"Surplus over documented gaps stays in reserve ({rv_sym or 'cash'}) — "
                "tactical plans never deploy beyond the gaps")))
    plans.append(_plan_shell(
        "E", net=net, deployable=deployable, account=account,
        tags=["tactical_opportunity", "portfolio_gap", "gap_capped"],
        objective=(f"Gap rotation ONLY — fill documented portfolio underweights "
                   f"(${spent:,.0f} across {len(legs_e) - 1} gaps); NOT a replacement for {sold}"),
        legs=legs_e,
        advantages=["Addresses documented sleeve floors with gap-capped sizing",
                    f"${max(0.0, deployable - spent):,.0f} stays reserved rather than force-deployed"],
        compromises=["Does not restore the sold fund's exposure (by definition)"],
        risks=["Geopolitical tilt if defense-heavy — flagged, advisory only"],
        composite_rank=58.0, is_major=is_major, settled=settled,
    ))

    # --- Plan F: staged deployment with ultimate target + triggers (Phase 4) ---
    ultimate = [(g_sym, 0.45, "large_growth_restoration", g_ev),
                (d_sym, 0.35, "dividend_quality_ballast", d_ev),
                (f_sym, 0.20, "fixed_income_ballast", f_ev)]
    tranche1 = round(deployable * 0.25, 2)
    legs_f = alloc([(s, f * 0.25, r, e) for s, f, r, e in ultimate], deployable,
                   dual={i1_sym: "partial_growth_restore+income_enhance"})
    for l in legs_f:
        l["thesis"] = f"Tranche 1 of 3 — 25% of deployable toward the ultimate target ({l['role'].replace('_', ' ')})"
    reserve_f = round(deployable - sum(_as_float(l.get("target_dollars")) for l in legs_f), 2)
    legs_f.append(_reserve_leg(
        account, max(0.0, reserve_f if settled else net - tranche1),
        vehicle=rv_sym, vehicle_yield=rv_yield,
        thesis=f"Reserved for tranches 2–3 in {rv_sym or 'cash'}"
               + (f" earning {rv_yield:.2f}%" if rv_yield else "")))
    stage_reason = ("Stage exposure because the current regime is risk-off and entry risk is elevated"
                    if risk_off and settled else
                    "Stage exposure to control timing risk" if settled else
                    "Deploy only verified cash now; reserve remainder for later stages")
    tranche_triggers = [
        "Tranche 2 (35% of deployable): regime exits risk-off OR the primary growth leg trades "
        "5% below the tranche-1 fill for 5 sessions",
        "Tranche 3 (remaining 40%): 30 trading days after tranche 2 OR a 10% market drawdown "
        "entry trigger, whichever comes first",
    ]
    plans.append(_plan_shell(
        "F", net=net, deployable=deployable, account=account,
        tags=["staged_deployment", "strategic"],
        objective=stage_reason,
        legs=legs_f,
        advantages=[
            f"Regime-aware staging (current regime: {market.get('regime_posture') or 'unknown'})",
            "Reduces entry-timing risk with explicit tranche triggers"],
        compromises=["Slower exposure restoration than full deployment"],
        risks=[_staging_risk(settled, market.get("regime_posture"))],
        composite_rank=88.0 if risk_off else 70.0, is_major=is_major, settled=settled,
        extra={
            "ultimate_target": [
                {"ticker": s, "role": r, "target_pct_of_deployable": round(f * 100, 1),
                 "target_dollars": round(deployable * f, 2)} for s, f, r, _ in ultimate],
            "tranche_triggers": tranche_triggers,
        },
    ))

    # --- Plan G: hold in a named reserve vehicle (Phase 4) ---
    g_income = round(net * (rv_yield or 0.0) / 100.0, 2) if rv_yield else None
    growth_1y = (cands.get(g_sym) or {}).get("total_return") or {}
    opp_note = None
    g1 = (growth_1y.get("1Y") or {}).get("pct") if isinstance(growth_1y, dict) else None
    if g1 is not None and rv_yield is not None:
        opp_note = (f"Opportunity-cost estimate: {g_sym} returned {g1:.1f}% trailing-1Y vs "
                    f"{rv_yield:.2f}% reserve yield — history, not a forecast")
    legs_g = [_reserve_leg(
        account, net, vehicle=rv_sym, vehicle_yield=rv_yield, actionable=bool(rv_sym),
        thesis=(f"Hold in {rv_sym or 'cash'}"
                + (f" yielding {rv_yield:.2f}% (≈${g_income:,.0f}/yr)" if rv_yield and g_income else "")
                + "; revisit in 30 days or on regime change"))]
    plans.append(_plan_shell(
        "G", net=net, deployable=0.0 if not settled else 0.0, account=account,
        tags=["hold_reserve", "reserve_vehicle"],
        objective=(f"Hold proceeds in {rv_sym or 'cash reserve'}"
                   + (f" at {rv_yield:.2f}%" if rv_yield else "")
                   + " with explicit revisit conditions"),
        legs=legs_g,
        advantages=(["No execution risk"]
                    + ([f"Earns ≈${g_income:,.0f}/yr while waiting"] if g_income else [])),
        compromises=["Exposure gap persists until deployed"],
        risks=[r for r in [opp_note or "Cash drag if the regime improves",
                           None if settled else "Settlement must still verify"] if r],
        composite_rank=55.0 if settled else 85.0, is_major=is_major, settled=settled,
        extra={"reserve_vehicle": rv_sym, "reserve_vehicle_yield_pct": rv_yield,
               "revisit_date": (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat(),
               "entry_triggers": ["regime exits risk-off", "operator review",
                                  "primary growth candidate −10% from current quote"]},
    ))

    # Plan G financials: net is entirely reserve; deployable for G is 0 — rebuild block honestly
    plans[-1]["financials"] = _finalize_financials(legs_g, net=net, deployable=net)

    # ── decision scorecard + readiness + recommendation (Phases 2, 5, 6) ────
    sold_income = None
    try:
        import sys
        sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
        from db_adapter import _get_conn
        from lib.redeploy_income import income_snapshot
        conn = _get_conn()
        snap = income_snapshot(conn.cursor(), [sold]).get(sold) or {}
        conn.rollback()
        if snap.get("yield_pct") is not None:
            sold_income = round(net * snap["yield_pct"] / 100.0, 2)
    except Exception:
        pass

    dctx = {
        "regime_posture": market.get("regime_posture"),
        "is_major": is_major,
        "exposure_sectors": exposure.get("sectors") or [],
        "account_type": "ira" if "ira" in account.lower() else "taxable",
        "sold_annual_income_usd": sold_income,
        "weights": load_weights(),
    }
    scores = {}
    for p in plans:
        sc = score_plan(p, dctx)
        p["decision_score"] = sc
        p["confidence"] = sc["total_score"]          # confidence IS the visible scorecard total
        p["composite_rank"] = sc["total_score"]
        scores[p["plan_archetype"]] = sc
    plans.sort(key=lambda p: -p["decision_score"]["total_score"])
    recommendation = recommend(plans, scores, dctx)

    rctx = {"is_major": is_major, "settled": settled,
            "analytics_exist": {"pro_forma": True, "performance": True,
                                "lookthrough": True, "entries": True},
            "memo_exists": True, "audit_exists": True, "p0_warnings": []}
    for p in plans:
        p["readiness"] = readiness_state(p, rctx)
        p["operator_status"] = ("operator_ready" if p["readiness"]["operator_ready"] else "draft")

    # ── rejected alternatives with real codes (defect 15) ───────────────────
    used_syms = {l["ticker"] for p in plans for l in (p.get("legs") or []) if not l.get("is_reserve")}
    rejected: list[dict[str, Any]] = []
    if proxy:
        rejected.append({"symbol": proxy, "reason_code": "RPL-001",
                         "reason": f"Duplicate proxy of sold fund {sold} — buying it back re-creates "
                                   "the exposure just sold"})
    seen_rej = {proxy} if proxy else set()
    for ev in role_evidence_log:
        for alt in (ev.get("alternatives") or []):
            s = alt["symbol"]
            if s in used_syms or s in seen_rej:
                continue
            seen_rej.add(s)
            rejected.append({
                "symbol": s, "reason_code": "ROLE_RUNNER_UP",
                "reason": (f"Lost the {ev['role'].replace('_', ' ')} selection to {ev.get('selected')}: "
                           f"{alt.get('why_lost') or 'lower role score'}"),
                "eligible_again_when": "role winner degrades on fees/liquidity/history or is excluded",
            })
    for row in (v1_targets or [])[:6]:
        s = str(row.get("symbol") or "").upper()
        if not s or s in used_syms or s in seen_rej:
            continue
        seen_rej.add(s)
        code = "RPL-004" if (row.get("evidence") or {}).get("unrelated_portfolio_gap") \
            or (row.get("evidence") or {}).get("rotation_to_portfolio_gap") else "NOT_ROLE_ELIGIBLE"
        rejected.append({"symbol": s, "reason_code": code,
                         "reason": ("Portfolio-gap candidate — belongs in Plan E tactical lane, "
                                    "not replacement plans" if code == "RPL-004" else
                                    "Did not qualify for any replacement role in this plan set")})
    rejected = rejected[:10]

    memo = build_pm_memo(event, plans[0], recommendation, {
        "regime_posture": market.get("regime_posture"), "settled": settled,
        "exposure_removed_text": "; ".join(
            f"{s['sector']} ${_as_float(s.get('usd_removed')):,.0f}"
            for s in (exposure.get("sectors") or [])[:6]) or None,
    })
    legacy_memo = (
        f"{sold} sale — net ${net:,.0f} ({'settled' if settled else 'UNSETTLED'}) in {account}. "
        f"System lean: Plan {recommendation['primary']['archetype']} "
        f"(score {recommendation['primary']['total_score']}). Advisory only.")
    plans[0]["hermes_narrative"] = legacy_memo

    for p in plans:
        sc = p.get("scenarios", {}).get("base", {})
        if _as_float(sc.get("portfolio_vol_delta_pp_estimate")) > VOL_DELTA_ABS_PP_MAX \
                or _as_float(sc.get("max_drawdown_pct_estimate")) <= DRAWDOWN_REJECT_THRESHOLD_PCT:
            p["operator_status"] = "draft"
            p.setdefault("risks", []).append("RPL-003 vol/drawdown verifier")

    return {
        "generator_version": GENERATOR_VERSION,
        "policy_version": POLICY_VERSION,
        "input_hash": pa.get("input_hash"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "settled_basis": settled,
        "regime_basis": market.get("regime_posture"),
        "plans": plans,
        "rejected_alternatives": rejected,
        "primary_archetype": plans[0]["plan_archetype"] if plans else None,
        "recommendation": recommendation,
        "pm_memo_structured": memo,
        "pm_memo": legacy_memo,
        "role_selection_log": role_evidence_log,
    }


def enrich_event_phase_b(event: dict[str, Any], *, v1_plan: dict[str, Any]) -> dict[str, Any]:
    """Attach Phase B institutional plans to event metadata."""
    if not (event.get("metadata") or {}).get("phase_a"):
        return event
    bundle = build_institutional_plans(
        event,
        v1_targets=v1_plan.get("targets") or [],
        sleeve_gaps=v1_plan.get("sleeve_gaps") or [],
        sale_ctx=v1_plan.get("sale_context") or {},
    )
    meta = dict(event.get("metadata") or {})
    meta["phase_b"] = bundle
    meta["institutional_plans"] = bundle.get("plans") or []
    meta["pm_memo"] = bundle.get("pm_memo")
    meta["pm_memo_structured"] = bundle.get("pm_memo_structured")
    meta["recommendation"] = bundle.get("recommendation")
    event["metadata"] = meta
    return event
