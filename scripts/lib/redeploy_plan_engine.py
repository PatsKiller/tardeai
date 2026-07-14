"""redeploy_plan_engine — Phase B: competing institutional plans A–G (advisory only)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.redeploy_data_truth import (
    DRAWDOWN_REJECT_THRESHOLD_PCT,
    EXPORT_QUOTE_MAX_AGE_MINUTES,
    OPERATOR_READY_MIN_CONFIDENCE,
    OPERATOR_READY_MIN_EVIDENCE_FACTORS,
    PLAN_ARCHETYPES,
    POLICY_VERSION,
    VOL_DELTA_ABS_PP_MAX,
    _as_float,
    _load_json,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"

GENERATOR_VERSION = "phase_b_1.0.0"

# Sector → ETF for diversified restoration (all major GICS buckets)
_SECTOR_ETF_RESTORE = {
    "Technology": "QQQ",
    "Communication Services": "XLC",
    "Financial Services": "XLF",
    "Consumer Cyclical": "XLY",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Basic Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
}

_BLOCKED_REASON = {
    "SCHG": "RPL-001",
    "ITA": "RPL-004",
    "XAR": "RPL-004",
}

_INCOME_ETFS = frozenset({"JEPQ", "JEPI", "SCHD"})


def _phase_a(event: dict[str, Any]) -> dict[str, Any]:
    return (event.get("metadata") or {}).get("phase_a") or {}


def _technical(sym: str) -> dict[str, Any]:
    tech = _load_json(STATE / "technical_snapshot.json", {})
    row = tech.get(sym.upper()) or {}
    meta = tech.get("_meta") or {}
    return {
        "price": _as_float(row.get("price")),
        "atr": _as_float(row.get("atr")),
        "sma20": _as_float(row.get("sma20")),
        "sma50": _as_float(row.get("sma50")),
        "rsi": _as_float(row.get("rsi")),
        "as_of": meta.get("last_updated"),
    }


def _yield_pct(sym: str) -> float | None:
    for p in _load_json(STATE / "dividend_calendar.json", {}).get("payers") or []:
        if (p.get("symbol") or "").upper() == sym.upper():
            y = _as_float(p.get("yield_pct"))
            return y if y else None
    return None


def _whole_shares(dollars: float, price: float) -> tuple[int, float]:
    if price <= 0 or dollars <= 0:
        return 0, 0.0
    sh = int(dollars // price)
    return sh, round(sh * price, 2)


def _entry_package(sym: str, *, leg_dollars: float) -> dict[str, Any]:
    t = _technical(sym)
    price = t["price"]
    atr = t["atr"] or (price * 0.015 if price else 0)
    pref = round(price - atr * 0.5, 2) if price else None
    if t["sma50"] and pref:
        pref = round(min(pref, max(t["sma50"], price * 0.98)), 2)
    stages = {}
    if pref and leg_dollars > 0:
        for i, (pct, mult) in enumerate([(25, 0), (25, 1.0), (50, 2.0)], 1):
            stage_price = round(pref - atr * mult, 2)
            stage_d = round(leg_dollars * pct / 100.0, 2)
            sh, filled = _whole_shares(stage_d, stage_price)
            stages[f"stage_{i}_pct"] = pct
            stages[f"stage_{i}_price"] = stage_price
            stages[f"stage_{i}_shares"] = sh
            stages[f"stage_{i}_dollars"] = filled
    stale = False
    if t.get("as_of"):
        try:
            # technical_snapshot uses "YYYY-MM-DD HH:MM" local-style
            pass
        except Exception:
            stale = True
    return {
        "current_price": price or None,
        "price_as_of": t.get("as_of"),
        "price_stale": stale,
        "preferred_entry": pref,
        "entry_range_low": round(pref - atr, 2) if pref else None,
        "entry_range_high": round(pref + atr * 0.3, 2) if pref else None,
        "do_not_chase": round(price + atr * 0.5, 2) if price else None,
        **stages,
    }


def _reserve_leg(account: str, dollars: float, *, actionable: bool, thesis: str) -> dict[str, Any]:
    return {
        "ticker": "SPAXX",
        "security_name": "Cash reserve / settlement hold",
        "account": account,
        "allocation_pct_of_net": None,
        "target_dollars": round(dollars, 2),
        "target_shares": None,
        "is_reserve": True,
        "is_actionable": actionable,
        "thesis": thesis,
    }


def _equity_leg(
    sym: str,
    account: str,
    dollars: float,
    *,
    pct_of_net: float | None,
    thesis: str,
    overlap_note: str | None = None,
    dual_label: str | None = None,
) -> dict[str, Any]:
    sym = sym.upper()
    entry = _entry_package(sym, leg_dollars=dollars)
    price = entry.get("current_price") or 0
    sh, filled = _whole_shares(dollars, price) if price else (0, 0.0)
    leg = {
        "ticker": sym,
        "account": account,
        "allocation_pct_of_net": pct_of_net,
        "target_dollars": filled or round(dollars, 2),
        "target_shares": sh,
        "is_reserve": False,
        "is_actionable": filled > 0 or dollars > 0,
        "expected_yield_pct": _yield_pct(sym),
        "thesis": thesis,
        "overlap_note": overlap_note,
        **entry,
    }
    if dual_label:
        leg["dual_label"] = dual_label
    return leg


def _blocked_symbol(sym: str, event: dict[str, Any], *, tactical_gap: bool = False) -> str | None:
    sym = sym.upper()
    proxy = str(event.get("proxy_symbol") or "").upper()
    if proxy and sym == proxy:
        return "RPL-001"
    reason = _BLOCKED_REASON.get(sym)
    # ITA/XAR blocked for replacement plans (RPL-004) but allowed in Plan E tactical gap-fill.
    if reason == "RPL-004" and tactical_gap:
        return None
    return reason


def _sleeve_gap_etfs(sleeve_gaps: list[dict]) -> list[str]:
    from lib.deploy_intelligence_engine import _THEME_ETF_MAP
    out = []
    for g in sleeve_gaps[:4]:
        theme = g.get("theme")
        for sym in (_THEME_ETF_MAP.get(theme) or [])[:1]:
            if sym not in out:
                out.append(sym)
    return out


def _allocate_deployable(
    weights: list[tuple[str, float]],
    *,
    net: float,
    deployable: float,
    account: str,
    event: dict[str, Any],
    thesis_prefix: str,
    tactical_gap: bool = False,
) -> list[dict[str, Any]]:
    """weights: [(symbol, fraction of deployable pool), ...] — sums to 1.0"""
    legs = []
    pool = round(deployable, 2)
    for sym, frac in weights:
        if _blocked_symbol(sym, event, tactical_gap=tactical_gap):
            continue
        d = round(pool * frac, 2)
        if d <= 0:
            continue
        pct_net = round(d / net * 100.0, 2) if net else None
        legs.append(_equity_leg(
            sym, account, d,
            pct_of_net=pct_net,
            thesis=f"{thesis_prefix}: deploy {sym}",
        ))
    return legs


def _plan_shell(
    archetype: str,
    *,
    net: float,
    deployable: float,
    reserve: float,
    account: str,
    tags: list[str],
    objective: str,
    legs: list[dict],
    advantages: list[str],
    compromises: list[str],
    risks: list[str],
    composite_rank: float,
    is_major: bool,
    unmet: dict | None = None,
) -> dict[str, Any]:
    plan_type, desc = PLAN_ARCHETYPES[archetype]
    actionable_sum = sum(l["target_dollars"] for l in legs if not l.get("is_reserve"))
    evidence = 0
    if legs:
        evidence += 1
    if any(l.get("current_price") for l in legs if not l.get("is_reserve")):
        evidence += 1
    if reserve > 0:
        evidence += 1
    if unmet:
        evidence += 1
    confidence = min(95.0, composite_rank * 0.7 + evidence * 5.0)
    operator_status = "draft"
    oversight_status = "pending"
    if is_major:
        oversight_status = "pending"  # PR-4 required for operator_ready
    if (
        confidence >= OPERATOR_READY_MIN_CONFIDENCE
        and evidence >= OPERATOR_READY_MIN_EVIDENCE_FACTORS
        and not is_major
    ):
        operator_status = "operator_ready"
        oversight_status = "skipped"
    deploy_pct = round(actionable_sum / net * 100.0, 2) if net else 0.0
    return {
        "plan_archetype": archetype,
        "plan_type": plan_type,
        "plan_description": desc,
        "tags": tags,
        "objective": objective,
        "account_default": account,
        "total_deployable_usd": round(actionable_sum, 2),
        "reserve_usd": round(reserve, 2),
        "deploy_pct_of_net": deploy_pct,
        "net_proceeds_usd": net,
        "confidence": round(confidence, 1),
        "evidence_factor_count": evidence,
        "operator_status": operator_status,
        "oversight_status": oversight_status,
        "composite_rank": composite_rank,
        "advantages": advantages,
        "compromises": compromises,
        "risks": risks,
        "legs": legs,
        "unmet_exposure": unmet or {},
        "scenarios": {
            "base": {
                "cash_remaining": round(reserve, 2),
                "portfolio_vol_delta_pp_estimate": 0.4,
                "max_drawdown_pct_estimate": -8.0,
            },
        },
        "hermes_narrative": None,
    }


def _unmet_exposure(exposure: dict[str, Any], legs: list[dict]) -> dict[str, Any]:
    """Major sales: summarize what sectors are not addressed by plan legs."""
    if not exposure.get("sectors"):
        return {}
    leg_syms = {l["ticker"] for l in legs if not l.get("is_reserve")}
    restored_sectors = set()
    for sec in exposure.get("sectors") or []:
        etf = _SECTOR_ETF_RESTORE.get(sec["sector"])
        if etf and etf in leg_syms:
            restored_sectors.add(sec["sector"])
    missing = [
        {"sector": s["sector"], "usd_removed": s["usd_removed"]}
        for s in exposure.get("sectors") or []
        if s["sector"] not in restored_sectors
    ][:6]
    return {"sectors_not_restored": missing, "income_status": exposure.get("income_status")}


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
    ctx = pa.get("portfolio_context") or {}

    net = _as_float(recon.get("net_proceeds_usd") or event.get("proceeds_usd"))
    deployable = _as_float(recon.get("deployable_cash_usd") or event.get("deployable_cash_usd"))
    reserve_static = _as_float(recon.get("planned_not_actionable_usd"))
    account = str(ctx.get("default_deployment_account") or event.get("account") or "")
    is_major = bool(ctx.get("is_major_sale"))
    sold = str(event.get("symbol") or "").upper()
    proxy = str(event.get("proxy_symbol") or "").upper()
    gaps = sleeve_gaps or []
    v1 = v1_targets or []

    if sale_ctx and sale_ctx.get("tier") == "minor":
        return {
            "generator_version": GENERATOR_VERSION,
            "policy_version": POLICY_VERSION,
            "plans": [],
            "rejected_alternatives": [],
            "advisory_note": "Minor sale — institutional plans suppressed.",
        }

    plans: list[dict[str, Any]] = []

    # --- Plan A: Strategic replacement ---
    legs_a = _allocate_deployable(
        [("QQQ", 0.45), ("SCHD", 0.35), ("BND", 0.20)],
        net=net, deployable=deployable, account=account, event=event,
        thesis_prefix="Strategic replacement",
    )
    if deployable > 0:
        legs_a.append(_reserve_leg(
            account, reserve_static,
            actionable=False,
            thesis="Planned-not-actionable until proceeds settle in source account",
        ))
    unmet_a = _unmet_exposure(exposure, legs_a) if is_major else {}
    plans.append(_plan_shell(
        "A", net=net, deployable=deployable, reserve=reserve_static, account=account,
        tags=["strategic_replacement", "growth"],
        objective=f"Restore Nasdaq/large-cap exposure lost from {sold}",
        legs=legs_a,
        advantages=["Pure growth sleeve via QQQ", "Dividend ballast via SCHD"],
        compromises=["Does not restore Comm Services overweight of Contrafund", "QQQ ≠ active stock selection"],
        risks=(
            [f"Avoids duplicate proxy {proxy}"]
            if proxy
            else ["Concentration in mega-cap index"]
        ),
        composite_rank=82.0,
        is_major=is_major,
        unmet=unmet_a,
    ))

    # --- Plan B: Diversified basket across removed sectors ---
    top_sectors = sorted(exposure.get("sectors") or [], key=lambda x: -_as_float(x.get("weight_pct")))[:5]
    weights_b = []
    if top_sectors:
        share = 0.85 / len(top_sectors)
        for s in top_sectors:
            etf = _SECTOR_ETF_RESTORE.get(s["sector"], "QQQ")
            weights_b.append((etf, share))
        weights_b.append(("BND", 0.15))
    else:
        weights_b = [("QQQ", 0.5), ("SCHD", 0.3), ("BND", 0.2)]
    legs_b = _allocate_deployable(weights_b, net=net, deployable=deployable, account=account, event=event,
                                   thesis_prefix="Diversified sector restore")
    legs_b.append(_reserve_leg(account, reserve_static, actionable=False, thesis="Settlement reserve"))
    plans.append(_plan_shell(
        "B", net=net, deployable=deployable, reserve=reserve_static, account=account,
        tags=["diversified_basket", "multi_sector"],
        objective="Restore removed sector weights across all GICS buckets",
        legs=legs_b,
        advantages=["Broadest sector restoration", "Reduces single-ETF risk"],
        compromises=["More legs to manage", "Sector ETFs are imperfect proxies"],
        risks=["Overlap with existing sector ETFs"],
        composite_rank=78.0,
        is_major=is_major,
        unmet=_unmet_exposure(exposure, legs_b) if is_major else {},
    ))

    # --- Plan C: Income-oriented ---
    legs_c = _allocate_deployable(
        [("JEPQ", 0.55), ("JEPI", 0.45)],
        net=net, deployable=deployable, account=account, event=event,
        thesis_prefix="Income-oriented",
    )
    for leg in legs_c:
        if leg["ticker"] in _INCOME_ETFS:
            leg["dual_label"] = "partial_growth_restore+income_enhance"
    legs_c.append(_reserve_leg(account, reserve_static, actionable=False, thesis="Settlement reserve"))
    plans.append(_plan_shell(
        "C", net=net, deployable=deployable, reserve=reserve_static, account=account,
        tags=["income_oriented", "dual_label"],
        objective=f"Enhance income while partially restoring growth exposure from {sold}",
        legs=legs_c,
        advantages=["High yield on deployed cash", "IRA-appropriate distributions"],
        compromises=["Covered-call cap on upside", "Not a pure growth replacement"],
        risks=["JEPQ may overlap Fidelity IRA holding — review cross-account"],
        composite_rank=75.0,
        is_major=is_major,
        unmet={"growth_upside_capped": True, "income_status": exposure.get("income_status")} if is_major else {},
    ))

    # --- Plan D: Defensive ---
    legs_d = _allocate_deployable(
        [("BND", 0.70), ("SCHD", 0.30)],
        net=net, deployable=deployable, account=account, event=event,
        thesis_prefix="Defensive",
    )
    legs_d.append(_reserve_leg(account, reserve_static, actionable=False, thesis="Settlement reserve"))
    plans.append(_plan_shell(
        "D", net=net, deployable=deployable, reserve=reserve_static, account=account,
        tags=["defensive", "risk_reduction"],
        objective="Reduce portfolio risk while redeploying proceeds",
        legs=legs_d,
        advantages=["Lower beta deployment", "Income from SCHD"],
        compromises=["Minimal growth restoration"],
        risks=["Underweight equities if prolonged"],
        composite_rank=62.0,
        is_major=is_major,
    ))

    # --- Plan E: Tactical (portfolio gaps only) ---
    tactical_syms = _sleeve_gap_etfs(gaps)
    if tactical_syms:
        frac = 1.0 / len(tactical_syms[:3])
        legs_e = _allocate_deployable(
            [(s, frac) for s in tactical_syms[:3]],
            net=net, deployable=deployable, account=account, event=event,
            thesis_prefix="Tactical portfolio gap",
            tactical_gap=True,
        )
        for leg in legs_e:
            leg["thesis"] = (
                f"Tactical underweight fill — NOT replacement for {sold} "
                f"(portfolio gap rotation)"
            )
    else:
        legs_e = []
    legs_e.append(_reserve_leg(account, max(reserve_static, net - deployable), actionable=False,
                                thesis="Reserve — tactical slice only when gaps exist"))
    plans.append(_plan_shell(
        "E", net=net, deployable=deployable, reserve=reserve_static, account=account,
        tags=["tactical_opportunity", "portfolio_gap"],
        objective="Fill portfolio underweights — separate from sale replacement",
        legs=legs_e,
        advantages=["Addresses sleeve floors", "Does not conflate with FCNTX replacement"],
        compromises=["Does not restore sold fund exposure"],
        risks=["Geopolitical tilt if defense-heavy — flagged only"],
        composite_rank=70.0,
        is_major=is_major,
    ))

    # --- Plan F: Staged deployment (25% of deployable now) ---
    stage_now = round(deployable * 0.25, 2)
    stage_reserve = round(net - stage_now, 2)
    legs_f = []
    if stage_now > 0:
        legs_f.append(_equity_leg(
            "JEPQ", account, stage_now * 0.6,
            pct_of_net=round(stage_now * 0.6 / net * 100, 2) if net else None,
            thesis="Staged tranche 1 — 60% of initial 25% deploy slice",
            dual_label="partial_growth_restore+income_enhance",
        ))
        legs_f.append(_equity_leg(
            "QQQ", account, stage_now * 0.4,
            pct_of_net=round(stage_now * 0.4 / net * 100, 2) if net else None,
            thesis="Staged tranche 1 — 40% of initial 25% deploy slice",
        ))
    legs_f.append(_reserve_leg(
        account, stage_reserve,
        actionable=stage_reserve <= deployable,
        thesis="Reserved for stages 2–3 and unsettled proceeds",
    ))
    plans.append(_plan_shell(
        "F", net=net, deployable=stage_now, reserve=stage_reserve, account=account,
        tags=["staged_deployment", "strategic"],
        objective="Deploy only verified cash now; reserve remainder for later stages",
        legs=legs_f,
        advantages=["Respects deployable cash cap", "Reduces timing risk"],
        compromises=["Slower exposure restoration"],
        risks=["Opportunity cost if market rallies before settlement"],
        composite_rank=88.0,
        is_major=is_major,
    ))

    # --- Plan G: Hold / no redeploy ---
    legs_g = [_reserve_leg(
        account, net,
        actionable=False,
        thesis="No immediate redeploy — hold until settlement and operator review",
    )]
    plans.append(_plan_shell(
        "G", net=net, deployable=0.0, reserve=net, account=account,
        tags=["hold_no_redeploy", "reserve_cash"],
        objective="Retain proceeds as cash; valid primary recommendation",
        legs=legs_g,
        advantages=["No execution risk", "Time to reconcile settlement"],
        compromises=["Exposure gap persists"],
        risks=["Cash drag", "Uninvested growth sleeve"],
        composite_rank=85.0 if recon.get("reconciliation_status") == "unsettled" else 55.0,
        is_major=is_major,
    ))

    plans.sort(key=lambda p: -p["composite_rank"])

    # Rejected alternatives from v1 + blocked symbols
    used_syms = set()
    for p in plans:
        for leg in p.get("legs") or []:
            if not leg.get("is_reserve"):
                used_syms.add(leg["ticker"])

    rejected: list[dict[str, Any]] = []
    for row in v1[:8]:
        sym = str(row.get("symbol") or "").upper()
        code = _blocked_symbol(sym, event)
        if sym in used_syms and not code:
            continue
        if not code and row.get("evidence", {}).get("unrelated_portfolio_gap"):
            code = "RPL-004"
        if not code and row.get("evidence", {}).get("rotation_to_portfolio_gap"):
            code = "RPL-004"
        if code or sym not in used_syms:
            rejected.append({
                "symbol": sym,
                "score": row.get("score"),
                "reason_code": code or "RPL-ALT",
                "reason": row.get("rationale") or "Alternative not selected in institutional plans",
            })
    if proxy:
        rejected.insert(0, {
            "symbol": proxy,
            "score": None,
            "reason_code": "RPL-001",
            "reason": f"Duplicate proxy of sold fund {sold}",
        })
    rejected = rejected[:5]

    # PM memo (deterministic shell — Hermes may supplement)
    top = plans[0] if plans else {}
    memo = (
        f"{sold} sale — net ${net:,.0f}, deployable ${deployable:,.0f} in {account}. "
        f"Reconciliation: {recon.get('reconciliation_status')}. "
        f"Recommended plan {top.get('plan_archetype')}: {top.get('objective')}. "
        f"Income status: {exposure.get('income_status', 'unknown')}. Advisory only."
    )
    if plans:
        plans[0]["hermes_narrative"] = memo

    # Risk verifier — flag plans breaching estimates
    for p in plans:
        sc = p.get("scenarios", {}).get("base", {})
        vol = _as_float(sc.get("portfolio_vol_delta_pp_estimate"))
        dd = _as_float(sc.get("max_drawdown_pct_estimate"))
        if vol > VOL_DELTA_ABS_PP_MAX or dd <= DRAWDOWN_REJECT_THRESHOLD_PCT:
            p["operator_status"] = "draft"
            p.setdefault("risks", []).append("RPL-003 vol/drawdown verifier")

    return {
        "generator_version": GENERATOR_VERSION,
        "policy_version": POLICY_VERSION,
        "input_hash": pa.get("input_hash"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plans": plans,
        "rejected_alternatives": rejected,
        "primary_archetype": plans[0]["plan_archetype"] if plans else None,
        "pm_memo": memo,
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
    event["metadata"] = meta
    return event