"""cio_institutional_sizing.py — Phase 6 institutional sizing v2.

Compute a set of CANDIDATE sizes and select among them with an explicit
rationale. Fire-clear / policy staging from v1 is preserved. A flat $5k ADD
or 10% trim is only a fallback candidate — never presented as optimized when
evidence is missing.

READ_ONLY_ADVISORY. Pure math — no broker execution.
"""
from __future__ import annotations

from typing import Any, Optional

SIZING_VERSION = "institutional_sizing_2.0.0"

# Policy defaults (aligned with capital_plan)
POLICY_CAP_PCT_DEFAULT = 12.0
CONCENTRATION_FIRE_PCT_DEFAULT = 16.5
# After clearing fire, leave a small buffer under the fire line when staging
FIRE_CLEAR_BUFFER_PP = 0.5  # percentage points under fire
# When only advisory TRIM and under policy: fallback fraction of position
FALLBACK_TRIM_FRACTION = 0.10
STAGED_FRACTION_OF_FULL_POLICY = 0.45  # staged between fire-clear and full policy
NEW_POSITION_DEFAULT_USD = 5_000.0

# ADD / RE_ENTER tranche geometry (advisory)
STARTER_USD = NEW_POSITION_DEFAULT_USD
TARGET_TRANCHE_MULTIPLE = 2.0  # target ≈ 2× starter, still bounded by policy

# Risk / liquidity defaults (used only when that evidence exists, except
# volatility_budget_size which always emits a number via assumed vol)
DEFAULT_ASSUMED_VOL = 0.20  # 20% annualized when vol is not supplied
DEFAULT_VOL_TARGET = 0.02  # 2% book vol contribution
DEFAULT_MAX_PARTICIPATION_PCT = 10.0  # % of ADV
TAXABLE_LARGE_GAIN_PCT = 20.0
TAXABLE_STAGE_SCALE = 0.70  # prefer smaller stage when large unrealized gain
IRA_STAGE_SCALE = 1.15  # allow larger stage in tax-advantaged accounts

# Candidate book — always present as keys; missing evidence → null
CANDIDATE_KEYS: tuple[str, ...] = (
    "minimum_risk_clear",
    "fire_safe",
    "policy_normalize",
    "tax_aware_lot_size",
    "risk_budget_size",
    "volatility_budget_size",
    "liquidity_max",
    "cash_policy_max",
    "replacement_opportunity_size",
    "default_fallback",
)

SIZING_QUALITY_HEURISTIC = "HEURISTIC"
SIZING_QUALITY_OBJECTIVE = "OBJECTIVE"
SIZING_QUALITY_OPTIMIZED = "OPTIMIZED"

TAX_ADVANTAGED_HINTS = (
    "tax_advantaged",
    "tax-advantaged",
    "ira",
    "roth",
    "401k",
    "401(k)",
    "rollover",
)


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _fopt(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _round_usd(v: Optional[float]) -> Optional[float]:
    if v is None:
        return None
    return round(float(v), 2)


def empty_candidates() -> dict[str, Optional[float]]:
    return {k: None for k in CANDIDATE_KEYS}


def normalize_tax_class(tax_class: Any) -> str:
    """Map free text / constraint prose to TAXABLE | TAX_ADVANTAGED."""
    raw = str(tax_class or "").strip().lower()
    if not raw:
        return "TAXABLE"
    if raw in ("tax_advantaged", "tax-advantaged", "ira", "roth", "401k"):
        return "TAX_ADVANTAGED"
    if any(h in raw for h in TAX_ADVANTAGED_HINTS) and "taxable" not in raw:
        return "TAX_ADVANTAGED"
    return "TAXABLE"


def normalize_vol(vol: Any) -> Optional[float]:
    """Accept decimal (0.22) or percent (22) annualized vol."""
    v = _fopt(vol)
    if v is None or v <= 0:
        return None
    if v > 2.0:
        v = v / 100.0
    return v if v > 0 else None


def normalize_lots(lots: Any) -> list[dict[str, Any]]:
    """Accept a list of lot dicts or a {id: lot} / {id: [lots]} map."""
    if not lots:
        return []
    if isinstance(lots, dict):
        out: list[dict[str, Any]] = []
        for v in lots.values():
            if isinstance(v, list):
                out.extend(x for x in v if isinstance(x, dict))
            elif isinstance(v, dict):
                out.append(v)
        return out
    if isinstance(lots, list):
        return [x for x in lots if isinstance(x, dict)]
    return []


def extract_sizing_inputs(src: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Pull optional v2 evidence fields off a position / queue / decision row."""
    p = src or {}
    nested = p.get("sizing") if isinstance(p.get("sizing"), dict) else {}
    get = lambda *keys: next(
        (p.get(k) for k in keys if p.get(k) is not None),
        next((nested.get(k) for k in keys if nested.get(k) is not None), None),
    )
    return {
        "lots": get("lots", "tax_lots"),
        "unrealized_gain_pct": get("unrealized_gain_pct", "gain_loss_pct"),
        "annualized_vol": get("annualized_vol", "vol", "volatility"),
        "risk_budget_usd": get("risk_budget_usd"),
        "adv_usd": get("adv_usd", "adv"),
        "cash_investable_usd": get("cash_investable_usd"),
        "cash_total_usd": get("cash_total_usd"),
        "cash_band_max_usd": get("cash_band_max_usd"),
        "cash_band_min_usd": get("cash_band_min_usd"),
        "replacement_opportunity_usd": get(
            "replacement_opportunity_usd", "replacement_opportunity_size",
        ),
        "max_participation_pct": get("max_participation_pct"),
        "vol_target": get("vol_target"),
    }


def _lot_market_value(lot: dict[str, Any]) -> float:
    mv = _fopt(lot.get("market_value") or lot.get("market_value_usd") or lot.get("value"))
    if mv is not None and mv > 0:
        return mv
    shares = _f(
        lot.get("shares_remaining") or lot.get("shares") or lot.get("quantity"),
        0.0,
    )
    price = _f(
        lot.get("price") or lot.get("current_price") or lot.get("mark"),
        0.0,
    )
    if shares > 0 and price > 0:
        return shares * price
    return 0.0


def _lot_gain_pct(lot: dict[str, Any], mv: float) -> float:
    gp = _fopt(
        lot.get("unrealized_gain_pct")
        if lot.get("unrealized_gain_pct") is not None
        else lot.get("gain_loss_pct")
        if lot.get("gain_loss_pct") is not None
        else lot.get("gain_pct")
    )
    if gp is not None:
        return gp
    shares = _f(
        lot.get("shares_remaining") or lot.get("shares") or lot.get("quantity"),
        0.0,
    )
    cost = _fopt(lot.get("total_cost") or lot.get("cost_basis"))
    if cost is None and shares > 0 and lot.get("cost_per_share") is not None:
        cost = _f(lot.get("cost_per_share")) * shares
    gain = _fopt(
        lot.get("unrealized_gain")
        if lot.get("unrealized_gain") is not None
        else lot.get("unrealized_gain_usd")
        if lot.get("unrealized_gain_usd") is not None
        else lot.get("gain_loss")
    )
    if gain is None and mv > 0 and cost is not None:
        gain = mv - cost
    if gain is None:
        return 0.0
    if cost is not None and cost > 0:
        return gain / cost * 100.0
    if mv > 0:
        return gain / mv * 100.0
    return 0.0


def _position_gain_pct(
    lots: list[dict[str, Any]],
    unrealized_gain_pct: Any,
) -> Optional[float]:
    gp = _fopt(unrealized_gain_pct)
    if gp is not None:
        return gp
    if not lots:
        return None
    parsed = []
    for lot in lots:
        mv = _lot_market_value(lot)
        if mv <= 0:
            continue
        parsed.append((mv, _lot_gain_pct(lot, mv)))
    if not parsed:
        return None
    tot = sum(mv for mv, _ in parsed)
    if tot <= 0:
        return None
    return sum(mv * g for mv, g in parsed) / tot


def tax_stage_scale(
    tax_class: Any,
    *,
    lots: Any = None,
    unrealized_gain_pct: Any = None,
) -> tuple[float, str, bool]:
    """Return (scale, note, tax_evidence).

    Scale is applied to the staged fraction only when lot / gain evidence exists
    so SCHD / policy dry tests stay bit-stable without tax inputs.
    """
    tc = normalize_tax_class(tax_class)
    parsed_lots = normalize_lots(lots)
    gain = _position_gain_pct(parsed_lots, unrealized_gain_pct)
    tax_evidence = bool(parsed_lots) or gain is not None

    if tc == "TAX_ADVANTAGED":
        note = (
            "IRA/tax-advantaged: larger stage allowed (no lot/tax drag on rebalance)."
        )
        scale = IRA_STAGE_SCALE if tax_evidence else 1.0
        return scale, note, tax_evidence
    if tax_evidence and gain is not None and gain >= TAXABLE_LARGE_GAIN_PCT:
        note = (
            f"Taxable with large unrealized gain ({gain:.1f}%): "
            "prefer a smaller stage before realizing."
        )
        return TAXABLE_STAGE_SCALE, note, True
    note = "Taxable: lot/tax review before full realization."
    return 1.0, note, tax_evidence


def compute_tax_aware_lot_size(
    lots: Any,
    tax_class: Any,
    target_usd: float,
) -> Optional[float]:
    """Lot-constrained size. Null when no lots are provided.

    Taxable: harvest losses / small-gain lots first; skip large-gain lots once
    any size is on the ticket. IRA: any lots, fill toward target.
    """
    parsed = normalize_lots(lots)
    if not parsed:
        return None
    rows: list[dict[str, float]] = []
    for lot in parsed:
        mv = _lot_market_value(lot)
        if mv <= 0:
            continue
        rows.append({"mv": mv, "gain_pct": _lot_gain_pct(lot, mv)})
    if not rows:
        return None

    target = max(0.0, _f(target_usd))
    tc = normalize_tax_class(tax_class)
    if tc == "TAXABLE":
        rows.sort(key=lambda r: r["gain_pct"])
        acc = 0.0
        for lot in rows:
            if acc >= target - 1e-9:
                break
            if lot["gain_pct"] >= TAXABLE_LARGE_GAIN_PCT and acc > 0:
                continue
            take = min(lot["mv"], target - acc)
            if lot["gain_pct"] >= TAXABLE_LARGE_GAIN_PCT:
                take = min(take, target * TAXABLE_STAGE_SCALE)
            acc += take
        if acc <= 0 and rows:
            acc = min(target * TAXABLE_STAGE_SCALE, rows[0]["mv"])
        return _round_usd(acc)

    # Tax-advantaged: operational fill, no gain ranking
    rows.sort(key=lambda r: -r["mv"])
    acc = 0.0
    for lot in rows:
        if acc >= target - 1e-9:
            break
        acc += min(lot["mv"], target - acc)
    return _round_usd(acc)


def _risk_budget_notional(risk_budget_usd: Any, vol: Optional[float]) -> Optional[float]:
    rb = _fopt(risk_budget_usd)
    if rb is None or rb <= 0 or vol is None or vol <= 0:
        return None
    return rb / vol


def _vol_budget_notional(
    portfolio_value_usd: float,
    vol: Optional[float],
    *,
    vol_target: Any = None,
    risk_budget_usd: Any = None,
) -> Optional[float]:
    """Inverse-vol notional. Uses assumed vol when the desk did not supply one."""
    p = max(0.0, _f(portfolio_value_usd))
    if p <= 0:
        return None
    asset_vol = vol if vol is not None and vol > 0 else DEFAULT_ASSUMED_VOL
    vt = normalize_vol(vol_target)
    if vt is None:
        rb = _fopt(risk_budget_usd)
        if rb is not None and rb > 0:
            vt = rb / p
        else:
            vt = DEFAULT_VOL_TARGET
    if vt <= 0 or asset_vol <= 0:
        return None
    return p * (vt / asset_vol)


def _liquidity_max(adv_usd: Any, max_participation_pct: Any) -> Optional[float]:
    adv = _fopt(adv_usd)
    if adv is None or adv <= 0:
        return None
    part = _f(max_participation_pct, DEFAULT_MAX_PARTICIPATION_PCT)
    if part <= 0:
        return None
    if part > 1.5:
        part = part / 100.0
    return adv * part


def compute_trim_objectives(
    *,
    market_value_usd: float,
    weight_pct: float,
    portfolio_value_usd: float,
    policy_cap_pct: float = POLICY_CAP_PCT_DEFAULT,
    fire_pct: float = CONCENTRATION_FIRE_PCT_DEFAULT,
) -> dict[str, Any]:
    """Dollar objectives for concentration / policy sizing."""
    v = max(0.0, _f(market_value_usd))
    p = max(0.0, _f(portfolio_value_usd))
    w = _f(weight_pct)
    if p > 0 and v > 0 and w <= 0:
        w = v / p * 100.0
    fire = _f(fire_pct, CONCENTRATION_FIRE_PCT_DEFAULT)
    cap = _f(policy_cap_pct, POLICY_CAP_PCT_DEFAULT)

    fire_value = p * fire / 100.0 if p > 0 else 0.0
    policy_value = p * cap / 100.0 if p > 0 else 0.0
    # Target slightly under fire when clearing (safety margin)
    fire_safe_value = p * max(0.0, fire - FIRE_CLEAR_BUFFER_PP) / 100.0 if p > 0 else 0.0

    trim_to_clear_fire = max(0.0, v - fire_value)
    trim_to_fire_safe = max(0.0, v - fire_safe_value)
    trim_to_policy = max(0.0, v - policy_value)
    fallback_10pct = round(v * FALLBACK_TRIM_FRACTION, 2)

    above_fire = w > fire + 1e-9
    above_policy = w > cap + 1e-9

    return {
        "sizing_version": SIZING_VERSION,
        "market_value_usd": round(v, 2),
        "weight_pct": round(w, 4),
        "portfolio_value_usd": round(p, 2),
        "fire_pct": fire,
        "policy_cap_pct": cap,
        "fire_value_usd": round(fire_value, 2),
        "policy_value_usd": round(policy_value, 2),
        "trim_to_clear_fire_usd": round(trim_to_clear_fire, 2),
        "trim_to_fire_safe_usd": round(trim_to_fire_safe, 2),
        "trim_to_policy_usd": round(trim_to_policy, 2),
        "fallback_10pct_usd": fallback_10pct,
        "above_fire": above_fire,
        "above_policy": above_policy,
    }


def _build_trim_candidates(
    obj: dict[str, Any],
    *,
    tax_class: str,
    lots: Any,
    unrealized_gain_pct: Any,
    annualized_vol: Any,
    risk_budget_usd: Any,
    adv_usd: Any,
    cash_investable_usd: Any,
    cash_total_usd: Any,
    cash_band_max_usd: Any,
    replacement_opportunity_usd: Any,
    max_participation_pct: Any,
    vol_target: Any,
    reference_target_usd: float,
) -> dict[str, Optional[float]]:
    v = obj["market_value_usd"]
    p = obj["portfolio_value_usd"]
    vol = normalize_vol(annualized_vol)
    c = empty_candidates()
    c["minimum_risk_clear"] = obj["trim_to_clear_fire_usd"]
    c["fire_safe"] = obj["trim_to_fire_safe_usd"]
    c["policy_normalize"] = obj["trim_to_policy_usd"]
    c["tax_aware_lot_size"] = compute_tax_aware_lot_size(
        lots, tax_class, reference_target_usd,
    )
    rb_notional = _risk_budget_notional(risk_budget_usd, vol)
    if rb_notional is not None:
        c["risk_budget_size"] = _round_usd(max(0.0, v - rb_notional))
    vol_notional = _vol_budget_notional(
        p, vol, vol_target=vol_target, risk_budget_usd=risk_budget_usd,
    )
    if vol_notional is not None:
        c["volatility_budget_size"] = _round_usd(max(0.0, v - vol_notional))
    c["liquidity_max"] = _round_usd(_liquidity_max(adv_usd, max_participation_pct))
    raise_room = _fopt(cash_band_max_usd)
    cash = _fopt(cash_total_usd)
    if raise_room is not None and cash is not None:
        c["cash_policy_max"] = _round_usd(max(0.0, raise_room - cash))
    elif _fopt(cash_investable_usd) is not None:
        # Investable is a deploy cap; trim raise is unconstrained by it —
        # fall back to full position as the cash-policy ceiling.
        c["cash_policy_max"] = _round_usd(v)
    else:
        c["cash_policy_max"] = _round_usd(v)
    c["replacement_opportunity_size"] = _round_usd(_fopt(replacement_opportunity_usd))
    c["default_fallback"] = obj["fallback_10pct_usd"]
    return c


def _evidence(
    *,
    lots: Any,
    unrealized_gain_pct: Any,
    annualized_vol: Any,
    risk_budget_usd: Any,
    adv_usd: Any,
    replacement_opportunity_usd: Any,
) -> dict[str, bool]:
    return {
        "has_lots": bool(normalize_lots(lots)),
        "has_unrealized_gain": _fopt(unrealized_gain_pct) is not None,
        "has_vol": normalize_vol(annualized_vol) is not None,
        "has_risk_budget": _fopt(risk_budget_usd) is not None and _f(risk_budget_usd) > 0,
        "has_adv": _fopt(adv_usd) is not None and _f(adv_usd) > 0,
        "has_replacement": _fopt(replacement_opportunity_usd) is not None,
    }


def _quality(ev: dict[str, bool], *, objective: bool) -> str:
    if ev["has_vol"] and ev["has_risk_budget"]:
        return SIZING_QUALITY_OPTIMIZED
    if objective:
        return SIZING_QUALITY_OBJECTIVE
    return SIZING_QUALITY_HEURISTIC


def _cap_by_liquidity_and_cash(
    recommended: float,
    candidates: dict[str, Optional[float]],
    *,
    is_add: bool,
) -> tuple[float, str, Optional[str]]:
    """Optionally bind the choice to liquidity / cash-policy caps."""
    note = ""
    bound_by: Optional[str] = None
    rec = recommended
    liq = candidates.get("liquidity_max")
    if liq is not None and rec > liq + 1e-9:
        rec = float(liq)
        note = f" Capped by liquidity_max (${liq:,.0f})."
        bound_by = "liquidity_max"
    cash_cap = candidates.get("cash_policy_max")
    if is_add and cash_cap is not None and rec > cash_cap + 1e-9:
        rec = float(cash_cap)
        note += f" Capped by cash_policy_max (${cash_cap:,.0f})."
        bound_by = "cash_policy_max"
    return rec, note, bound_by


def recommend_trim(
    *,
    market_value_usd: float,
    weight_pct: float,
    portfolio_value_usd: float,
    policy_cap_pct: float = POLICY_CAP_PCT_DEFAULT,
    fire_pct: float = CONCENTRATION_FIRE_PCT_DEFAULT,
    tax_class: str = "TAXABLE",
    advisory_trim: bool = True,
    lots: Any = None,
    unrealized_gain_pct: Any = None,
    annualized_vol: Any = None,
    risk_budget_usd: Any = None,
    adv_usd: Any = None,
    cash_investable_usd: Any = None,
    cash_total_usd: Any = None,
    cash_band_max_usd: Any = None,
    cash_band_min_usd: Any = None,  # accepted for API symmetry; unused on trim
    replacement_opportunity_usd: Any = None,
    max_participation_pct: Any = None,
    vol_target: Any = None,
) -> dict[str, Any]:
    """Choose a recommended trim among candidates (not a lone blind 10%)."""
    del cash_band_min_usd  # API symmetry with ADD / size_decision
    obj = compute_trim_objectives(
        market_value_usd=market_value_usd,
        weight_pct=weight_pct,
        portfolio_value_usd=portfolio_value_usd,
        policy_cap_pct=policy_cap_pct,
        fire_pct=fire_pct,
    )
    v = obj["market_value_usd"]
    clear = obj["trim_to_clear_fire_usd"]
    safe = obj["trim_to_fire_safe_usd"]
    full = obj["trim_to_policy_usd"]
    fb = obj["fallback_10pct_usd"]
    tc = normalize_tax_class(tax_class)
    scale, tax_note, tax_evidence = tax_stage_scale(
        tax_class, lots=lots, unrealized_gain_pct=unrealized_gain_pct,
    )
    ev = _evidence(
        lots=lots,
        unrealized_gain_pct=unrealized_gain_pct,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
    )

    why_not_min = ""
    why_not_max = ""
    method = "fallback_10pct"
    recommended = fb
    target_weight = obj["policy_cap_pct"]
    selected_candidate = "default_fallback"
    selection_rationale = ""
    objective = False

    if obj["above_fire"]:
        method = "clear_fire_staged"
        objective = True
        min_obj = max(clear, safe) if safe > 0 else clear
        if full > min_obj + 1.0:
            frac = STAGED_FRACTION_OF_FULL_POLICY
            if tax_evidence:
                frac = min(1.0, max(0.0, frac * scale))
            recommended = round(min_obj + frac * (full - min_obj), 2)
            selected_candidate = "staged_fire_to_policy"
            why_not_min = (
                f"Minimum to clear fire (${min_obj:,.0f}) leaves little safety margin "
                f"under the {obj['fire_pct']}% fire line."
            )
            why_not_max = (
                f"Full normalization to policy max {obj['policy_cap_pct']}% "
                f"(${full:,.0f}) may be more than needed in one step given conviction "
                f"and tax/account constraints."
            )
            if tc == "TAXABLE":
                why_not_max += " Taxable account: lot/tax review before full realization."
            elif tc == "TAX_ADVANTAGED":
                why_not_max += " " + tax_note
            selection_rationale = (
                f"Chose staged size ${recommended:,.0f} among candidates "
                f"(minimum_risk_clear=${clear:,.0f}, fire_safe=${safe:,.0f}, "
                f"policy_normalize=${full:,.0f}, default_fallback=${fb:,.0f}). "
                f"Fire binds: stay at or above fire-clear, below a full policy dump."
            )
            if tax_evidence:
                selection_rationale += " " + tax_note
        else:
            recommended = round(min_obj, 2)
            selected_candidate = "fire_safe" if safe >= clear else "minimum_risk_clear"
            why_not_min = "Clearing fire is the binding objective."
            why_not_max = "Already at or near policy once fire is cleared."
            selection_rationale = (
                f"Chose {selected_candidate} ${recommended:,.0f}: fire is binding "
                f"and policy is already nearby."
            )
        if portfolio_value_usd > 0:
            target_weight = max(
                0.0,
                (v - recommended) / portfolio_value_usd * 100.0,
            )
    elif obj["above_policy"]:
        method = "policy_normalize_staged"
        objective = True
        if full > 0:
            recommended = round(max(full * STAGED_FRACTION_OF_FULL_POLICY, min(fb, full)), 2)
            if tax_evidence:
                frac = min(1.0, max(0.0, STAGED_FRACTION_OF_FULL_POLICY * scale))
                staged = full * frac
                recommended = round(max(staged, min(fb, full) if scale >= 1.0 else staged), 2)
            recommended = min(recommended, full)
        else:
            recommended = 0.0
        selected_candidate = "policy_normalize" if abs(recommended - full) < 1.0 else "staged_to_policy"
        why_not_min = (
            f"A token trim below the excess over policy "
            f"(${full:,.0f} to fully normalize) does not restore the policy cap."
        )
        why_not_max = (
            f"Full cut to {obj['policy_cap_pct']}% (${full:,.0f}) in one step may be "
            f"oversized relative to desk conviction and replacement capital."
        )
        if tc == "TAXABLE":
            why_not_max += " Taxable account: lot/tax review before full realization."
        elif tc == "TAX_ADVANTAGED":
            why_not_max += " " + tax_note
        selection_rationale = (
            f"Chose ${recommended:,.0f} staged toward policy_normalize=${full:,.0f} "
            f"(default_fallback=${fb:,.0f}). Weight is above policy, below fire."
        )
        if tax_evidence:
            selection_rationale += " " + tax_note
        if portfolio_value_usd > 0:
            target_weight = max(0.0, (v - recommended) / portfolio_value_usd * 100.0)
    elif advisory_trim:
        method = "advisory_fallback_10pct"
        recommended = fb
        selected_candidate = "default_fallback"
        why_not_min = "No concentration fire; advisory trim uses the 10% fallback candidate only."
        why_not_max = "Position is within policy cap; larger cuts need a stronger objective."
        if tc == "TAXABLE":
            why_not_max += " Taxable: lot/tax review still applies."
        elif tc == "TAX_ADVANTAGED":
            why_not_max += " IRA: no tax drag, but no concentration objective either."
        target_weight = obj["weight_pct"] * (1.0 - FALLBACK_TRIM_FRACTION)
        selection_rationale = (
            f"Chose default_fallback ${recommended:,.0f} — within policy and fire, "
            f"so 10% is only a fallback candidate, not an optimized size."
        )
    else:
        method = "none"
        recommended = 0.0
        selected_candidate = "default_fallback"
        why_not_min = why_not_max = "No trim objective."
        selection_rationale = "No trim objective; selected $0."

    # Candidates use the pre-cap recommended as the tax-lot reference target
    candidates = _build_trim_candidates(
        obj,
        tax_class=tc,
        lots=lots,
        unrealized_gain_pct=unrealized_gain_pct,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        cash_investable_usd=cash_investable_usd,
        cash_total_usd=cash_total_usd,
        cash_band_max_usd=cash_band_max_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
        max_participation_pct=max_participation_pct or DEFAULT_MAX_PARTICIPATION_PCT,
        vol_target=vol_target,
        reference_target_usd=recommended if recommended > 0 else max(safe, full, fb),
    )

    recommended, cap_note, bound_by = _cap_by_liquidity_and_cash(
        recommended, candidates, is_add=False,
    )
    if cap_note:
        selection_rationale += cap_note
        if bound_by:
            selected_candidate = bound_by

    recommended = round(max(0.0, min(recommended, v)), 2)
    quality = _quality(ev, objective=objective)
    fallback_only = method == "advisory_fallback_10pct"

    return {
        **obj,
        "recommended_trim_usd": recommended,
        "recommended_delta_usd": -recommended if recommended > 0 else 0.0,
        "target_weight_pct": round(target_weight, 2),
        "method": method,
        "why_not_min": why_not_min,
        "why_not_max": why_not_max,
        "objective_summary": (
            f"Current weight {obj['weight_pct']:.2f}% · Fire {obj['fire_pct']}% · "
            f"Policy max {obj['policy_cap_pct']}% · "
            f"Min clear fire ${obj['trim_to_clear_fire_usd']:,.0f} · "
            f"Full to policy ${obj['trim_to_policy_usd']:,.0f} · "
            f"Alex recommend ${recommended:,.0f} ({method})"
        ),
        "fallback_candidate_only": fallback_only,
        "candidates": candidates,
        "selected_candidate": selected_candidate,
        "selection_rationale": selection_rationale.strip(),
        "sizing_quality": quality,
        "tax_class": tc,
        "evidence": ev,
        "insufficient_evidence": quality == SIZING_QUALITY_HEURISTIC,
        "tranches": None,
    }


def recommend_exit(
    *,
    market_value_usd: float,
    lots: Any = None,
    tax_class: str = "TAXABLE",
    annualized_vol: Any = None,
    risk_budget_usd: Any = None,
    adv_usd: Any = None,
    cash_investable_usd: Any = None,
    cash_total_usd: Any = None,
    cash_band_max_usd: Any = None,
    replacement_opportunity_usd: Any = None,
    max_participation_pct: Any = None,
    vol_target: Any = None,
    portfolio_value_usd: float = 0.0,
    unrealized_gain_pct: Any = None,
) -> dict[str, Any]:
    v = max(0.0, _f(market_value_usd))
    tc = normalize_tax_class(tax_class)
    ev = _evidence(
        lots=lots,
        unrealized_gain_pct=unrealized_gain_pct,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
    )
    candidates = empty_candidates()
    candidates["minimum_risk_clear"] = _round_usd(v)
    candidates["fire_safe"] = _round_usd(v)
    candidates["policy_normalize"] = _round_usd(v)
    candidates["tax_aware_lot_size"] = compute_tax_aware_lot_size(lots, tc, v)
    vol = normalize_vol(annualized_vol)
    rb_notional = _risk_budget_notional(risk_budget_usd, vol)
    if rb_notional is not None:
        candidates["risk_budget_size"] = _round_usd(max(0.0, v - rb_notional))
    vol_notional = _vol_budget_notional(
        _f(portfolio_value_usd), vol, vol_target=vol_target, risk_budget_usd=risk_budget_usd,
    )
    if vol_notional is not None:
        candidates["volatility_budget_size"] = _round_usd(max(0.0, v - vol_notional))
    candidates["liquidity_max"] = _round_usd(
        _liquidity_max(adv_usd, max_participation_pct or DEFAULT_MAX_PARTICIPATION_PCT)
    )
    candidates["cash_policy_max"] = _round_usd(v)
    candidates["replacement_opportunity_size"] = _round_usd(_fopt(replacement_opportunity_usd))
    candidates["default_fallback"] = _round_usd(v)
    rationale = (
        f"Chose full exit ${v:,.0f} (policy_normalize / default_fallback). "
        "Desk marked EXIT — residual book risk is not a candidate."
    )
    if tc == "TAXABLE":
        rationale += " Taxable: lot/tax review before realizing the full book."
    else:
        rationale += " IRA/tax-advantaged: no lot/tax drag on a full exit."
    return {
        "sizing_version": SIZING_VERSION,
        "method": "full_exit",
        "recommended_delta_usd": -v,
        "recommended_trim_usd": v,
        "target_weight_pct": 0.0,
        "objective_summary": f"Full exit of ${v:,.0f}",
        "why_not_min": "Partial exit would leave residual book risk the desk marked EXIT.",
        "why_not_max": "Already 100% of position.",
        "fallback_candidate_only": False,
        "candidates": candidates,
        "selected_candidate": "policy_normalize",
        "selection_rationale": rationale,
        "sizing_quality": SIZING_QUALITY_OBJECTIVE,
        "tax_class": tc,
        "evidence": ev,
        "insufficient_evidence": False,
        "tranches": None,
    }


def _build_add_candidates(
    *,
    headroom: float,
    default_usd: float,
    market_value_usd: float,
    portfolio_value_usd: float,
    tax_class: str,
    lots: Any,
    annualized_vol: Any,
    risk_budget_usd: Any,
    adv_usd: Any,
    cash_investable_usd: Any,
    cash_total_usd: Any,
    cash_band_max_usd: Any,
    replacement_opportunity_usd: Any,
    max_participation_pct: Any,
    vol_target: Any,
) -> dict[str, Optional[float]]:
    c = empty_candidates()
    # ADD has no fire-clear / fire-safe trim objective
    c["minimum_risk_clear"] = None
    c["fire_safe"] = None
    c["policy_normalize"] = _round_usd(headroom)
    c["tax_aware_lot_size"] = compute_tax_aware_lot_size(lots, tax_class, default_usd)
    vol = normalize_vol(annualized_vol)
    rb_notional = _risk_budget_notional(risk_budget_usd, vol)
    if rb_notional is not None:
        # Add toward the risk-budget notional, never above headroom
        add_rb = max(0.0, rb_notional - max(0.0, market_value_usd))
        c["risk_budget_size"] = _round_usd(min(add_rb, headroom) if headroom > 0 else add_rb)
    vol_notional = _vol_budget_notional(
        portfolio_value_usd, vol, vol_target=vol_target, risk_budget_usd=risk_budget_usd,
    )
    if vol_notional is not None:
        add_vol = max(0.0, vol_notional - max(0.0, market_value_usd))
        c["volatility_budget_size"] = _round_usd(
            min(add_vol, headroom) if headroom > 0 else add_vol
        )
    c["liquidity_max"] = _round_usd(
        _liquidity_max(adv_usd, max_participation_pct or DEFAULT_MAX_PARTICIPATION_PCT)
    )
    investable = _fopt(cash_investable_usd)
    if investable is not None:
        c["cash_policy_max"] = _round_usd(max(0.0, investable))
    elif _fopt(cash_band_max_usd) is not None and _fopt(cash_total_usd) is not None:
        # Room down toward cash-band max is not an add cap; investable-style
        # room is cash above the floor, which we do not have — use headroom.
        c["cash_policy_max"] = _round_usd(headroom)
    else:
        c["cash_policy_max"] = _round_usd(headroom)
    c["replacement_opportunity_size"] = _round_usd(_fopt(replacement_opportunity_usd))
    c["default_fallback"] = _round_usd(default_usd)
    return c


def recommend_add(
    *,
    headroom_usd: float,
    default_usd: float = NEW_POSITION_DEFAULT_USD,
    market_value_usd: float = 0.0,
    portfolio_value_usd: float = 0.0,
    tax_class: str = "TAXABLE",
    lots: Any = None,
    unrealized_gain_pct: Any = None,
    annualized_vol: Any = None,
    risk_budget_usd: Any = None,
    adv_usd: Any = None,
    cash_investable_usd: Any = None,
    cash_total_usd: Any = None,
    cash_band_max_usd: Any = None,
    cash_band_min_usd: Any = None,
    replacement_opportunity_usd: Any = None,
    max_participation_pct: Any = None,
    vol_target: Any = None,
) -> dict[str, Any]:
    """ADD / RE_ENTER: starter / target / max_policy / risk_budget tranches.

    A flat $5k is the starter / default_fallback candidate only. It is labeled
    HEURISTIC / fallback_candidate_only unless a risk budget (and vol) exist.
    """
    del cash_band_min_usd
    h = max(0.0, _f(headroom_usd))
    d = max(0.0, _f(default_usd, NEW_POSITION_DEFAULT_USD))
    tc = normalize_tax_class(tax_class)
    ev = _evidence(
        lots=lots,
        unrealized_gain_pct=unrealized_gain_pct,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
    )
    candidates = _build_add_candidates(
        headroom=h,
        default_usd=d,
        market_value_usd=_f(market_value_usd),
        portfolio_value_usd=_f(portfolio_value_usd),
        tax_class=tc,
        lots=lots,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        cash_investable_usd=cash_investable_usd,
        cash_total_usd=cash_total_usd,
        cash_band_max_usd=cash_band_max_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
        max_participation_pct=max_participation_pct,
        vol_target=vol_target,
    )

    def _bound(amt: float) -> float:
        x = amt
        if h > 0:
            x = min(x, h)
        else:
            x = 0.0
        liq = candidates.get("liquidity_max")
        if liq is not None:
            x = min(x, float(liq))
        cash_cap = candidates.get("cash_policy_max")
        if cash_cap is not None:
            x = min(x, float(cash_cap))
        return round(max(0.0, x), 2)

    starter = _bound(d)
    max_policy = _bound(h)
    target = _bound(max(d * TARGET_TRANCHE_MULTIPLE, starter))
    risk_budget_tranche = candidates.get("risk_budget_size")
    if risk_budget_tranche is not None:
        risk_budget_tranche = _bound(float(risk_budget_tranche))

    tranches = {
        "starter": starter,
        "target": target,
        "max_policy": max_policy,
        "risk_budget": risk_budget_tranche,
    }

    has_rb = ev["has_risk_budget"] and ev["has_vol"] and risk_budget_tranche is not None
    if has_rb:
        amt = _bound(float(risk_budget_tranche))
        method = "risk_budgeted_tranche"
        selected_candidate = "risk_budget_size"
        quality = SIZING_QUALITY_OPTIMIZED
        fallback = False
        selection_rationale = (
            f"Chose risk_budget_size ${amt:,.0f} among ADD candidates "
            f"(starter=${starter:,.0f}, target=${target:,.0f}, "
            f"max_policy=${max_policy:,.0f}, default_fallback=${d:,.0f}). "
            "Vol + risk budget present — not a flat $5k heuristic."
        )
    else:
        amt = starter
        method = "heuristic_starter_tranche"
        selected_candidate = "default_fallback"
        quality = SIZING_QUALITY_HEURISTIC
        fallback = True
        selection_rationale = (
            f"Chose starter / default_fallback ${amt:,.0f} among ADD candidates "
            f"(target=${target:,.0f}, max_policy=${max_policy:,.0f}, "
            f"risk_budget=null). No risk budget — $5k is HEURISTIC / "
            f"fallback_candidate_only, not an optimized size."
        )

    _, tax_note, _ = tax_stage_scale(
        tax_class, lots=lots, unrealized_gain_pct=unrealized_gain_pct,
    )
    if tc == "TAX_ADVANTAGED":
        selection_rationale += " " + tax_note
    else:
        selection_rationale += " Taxable: buy-side only; no gain realization."

    return {
        "sizing_version": SIZING_VERSION,
        "method": method,
        "recommended_delta_usd": amt,
        "objective_summary": (
            f"Add ${amt:,.0f} · starter ${starter:,.0f} · target ${target:,.0f} · "
            f"max_policy ${max_policy:,.0f} · risk_budget "
            f"{('$'+format(risk_budget_tranche, ',.0f')) if risk_budget_tranche is not None else 'n/a'} "
            f"({method})"
        ),
        "fallback_candidate_only": fallback,
        "candidates": candidates,
        "selected_candidate": selected_candidate,
        "selection_rationale": selection_rationale.strip(),
        "sizing_quality": quality,
        "tax_class": tc,
        "evidence": ev,
        "insufficient_evidence": quality == SIZING_QUALITY_HEURISTIC,
        "tranches": tranches,
        "why_not_min": (
            "A token add below the starter tranche is noise relative to ticket costs "
            "and does not establish a working position."
        ),
        "why_not_max": (
            f"max_policy ${max_policy:,.0f} is single-name headroom; filling it in "
            "one step is not justified without a risk budget."
        ),
    }


def size_decision(
    *,
    stance: str,
    market_value_usd: float,
    weight_pct: float,
    portfolio_value_usd: float,
    policy_cap_pct: float = POLICY_CAP_PCT_DEFAULT,
    fire_pct: float = CONCENTRATION_FIRE_PCT_DEFAULT,
    tax_class: str = "TAXABLE",
    headroom_usd: float = 0.0,
    lots: Any = None,
    unrealized_gain_pct: Any = None,
    annualized_vol: Any = None,
    risk_budget_usd: Any = None,
    adv_usd: Any = None,
    cash_investable_usd: Any = None,
    cash_total_usd: Any = None,
    cash_band_max_usd: Any = None,
    cash_band_min_usd: Any = None,
    replacement_opportunity_usd: Any = None,
    max_participation_pct: Any = None,
    vol_target: Any = None,
    advisory_trim: bool = True,
) -> dict[str, Any]:
    """Dispatch sizing by stance. Always returns a candidates dict."""
    s = (stance or "HOLD").upper()
    extras = dict(
        lots=lots,
        unrealized_gain_pct=unrealized_gain_pct,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        cash_investable_usd=cash_investable_usd,
        cash_total_usd=cash_total_usd,
        cash_band_max_usd=cash_band_max_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
        max_participation_pct=max_participation_pct,
        vol_target=vol_target,
    )
    if s == "EXIT":
        return recommend_exit(
            market_value_usd=market_value_usd,
            tax_class=tax_class,
            portfolio_value_usd=portfolio_value_usd,
            **extras,
        )
    if s == "TRIM":
        return recommend_trim(
            market_value_usd=market_value_usd,
            weight_pct=weight_pct,
            portfolio_value_usd=portfolio_value_usd,
            policy_cap_pct=policy_cap_pct,
            fire_pct=fire_pct,
            tax_class=tax_class,
            advisory_trim=advisory_trim,
            cash_band_min_usd=cash_band_min_usd,
            **extras,
        )
    if s in ("ADD", "RE_ENTER"):
        return recommend_add(
            headroom_usd=headroom_usd,
            market_value_usd=market_value_usd,
            portfolio_value_usd=portfolio_value_usd,
            tax_class=tax_class,
            cash_band_min_usd=cash_band_min_usd,
            **extras,
        )
    ev = _evidence(
        lots=lots,
        unrealized_gain_pct=unrealized_gain_pct,
        annualized_vol=annualized_vol,
        risk_budget_usd=risk_budget_usd,
        adv_usd=adv_usd,
        replacement_opportunity_usd=replacement_opportunity_usd,
    )
    return {
        "sizing_version": SIZING_VERSION,
        "method": "hold",
        "recommended_delta_usd": 0.0,
        "target_weight_pct": round(_f(weight_pct), 2),
        "objective_summary": "Hold — no size change",
        "fallback_candidate_only": False,
        "candidates": empty_candidates(),
        "selected_candidate": None,
        "selection_rationale": "Hold — no candidate selected.",
        "sizing_quality": SIZING_QUALITY_HEURISTIC,
        "tax_class": normalize_tax_class(tax_class),
        "evidence": ev,
        "insufficient_evidence": True,
        "tranches": None,
        "why_not_min": "No size change.",
        "why_not_max": "No size change.",
    }
