"""cio_capital_plan.py — Alex's capital plan + portfolio decision engine (Phase 6).

Turns "what should I do with my money?" into a deterministic, advisory-only
Capital Plan projection expressed in explicit dollars, with sources and uses of
funds shown together and a per-holding Position Decision table.

The plan composes canonical state that already exists elsewhere:

  * holdings.json            → portfolio value, cash, positions, account tax type
  * redeploy_capital_book    → sale proceeds awaiting redeploy (maturities/distributions)
  * cio_opportunity_queue    → desk verdicts (ADD / TRIM / EXIT / RE_ENTER)
  * cio_sector_opportunity   → sector rotation (underweight canonical GICS sectors)
  * risk posture (thesis)    → cash band floor, single-name / concentration caps

Every pure function is deterministic and separated from the live readers, so the
whole engine is dry-testable with no live DB / broker / LLM. It never promotes,
mutates, or executes — `READ_ONLY_ADVISORY` only.

Arithmetic model (deterministic, fail-closed toward caution) — capital_plan_1.1.0:

  cash_total       = settled cash from holdings (canonical; includes earmarked proceeds)
  reserve_usd      = portfolio_value * cash_band_min_pct / 100      (policy floor)
  investable_usd   = max(0, cash_total - reserve_usd)               (dry powder above floor)

  Earmarked vs prospective (Phase 2 double-count fix):
    earmarked_redeploy_usd = open redeploy remaining_usd already sitting IN cash_total
                             → LABEL only, never added again as "raise"
    prospective_trims/exits = not yet cash (true future raise)

  sources of funds:
    trims          = advisory TRIM  → trim_fraction of each trimmed position value (prospective)
    exits          = advisory EXIT  → 100% of each exited position value (prospective)
    maturities     = open redeploy remaining_usd (earmarked; already in cash)
    total_prospective_raise_usd = trims + exits
    total_raise_usd             = total_prospective_raise_usd   (NOT + maturities)

  uses of funds (deploy requests):
    adds / new_positions / reentry / sector_rotation (as before)
    reserve = reserve_usd (held back, not deployed)

  deployable                   = investable_usd + total_prospective_raise_usd
  net_recommended_deploy_usd   = min(total_uses, deployable)
  net_recommended_raise_usd    = total_prospective_raise_usd
  post_plan_cash_usd           = cash_total + prospective_raise - net_deploy
  post_plan_cash_pct           = post_plan_cash_usd / portfolio_value * 100

Invariant: earmarked_redeploy_usd <= cash_total + 0.01
Invariant: post_plan_cash_usd ≈ cash_total + net_raise - net_deploy

Cash is never force-deployed: if there are no uses (no adds/new/reentry/rotation
signal), `net_recommended_deploy_usd` is 0 even when investable cash exists.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

# Executor signature matches db_adapter._execute(sql, params=None, fetch=None).
Executor = Callable[..., Any]

CAPITAL_PLAN_VERSION = "capital_plan_1.3.0"  # Phase 6–13: account ledger + strategy context

# ── Policy defaults (overridden by thesis risk_posture_structured when present) ──
CASH_BAND_DEFAULT_MIN_PCT = 20.0
CASH_BAND_DEFAULT_MAX_PCT = 25.0
MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT = 12.0
CONCENTRATION_FIRE_PCT_DEFAULT = 16.5

# Advisory trim sizing: a TRIM verdict reduces a position by this fraction of its
# current value (rotation_sector_targets.trim_band low/high are 5-15%; use the
# midpoint when no explicit dollar target is supplied).
TRIM_FRACTION = 0.10
TRIM_BAND_LOW = 0.05
TRIM_BAND_HIGH = 0.15

# Default advisory starting size for a brand-new position / re-entry when the
# desk gives no dollar target. Bounded later by single-name headroom.
NEW_POSITION_DEFAULT_USD = 5_000.0

# Verdicts the desks can emit (mirror cio_opportunity_queue.ACTIONABLE_VERDICTS).
ACTIONABLE_VERDICTS = frozenset({"ADD", "TRIM", "EXIT", "RE_ENTER"})

# Re-entry states that count as a new-position use (mirror cio_opportunity_queue).
# Desk readiness states (READY TO REVIEW / NEAR ENTRY / OVERSOLD REVIEW) are NOT
# re-entry authority. Only an explicit RE_ENTER verdict authorizes re-entry.
ACTIONABLE_REENTRY_STATES: frozenset[str] = frozenset()

# Account `type` values that are tax-advantaged; everything else (or unknown) is
# treated as taxable so tax/lot constraints are never silently waived.
TAX_ADVANTAGED_TYPES = frozenset({
    "rollover_ira", "roth_ira", "ira", "traditional_ira", "401k", "401(k)", "sep_ira",
})

# Default review cadence for the Position Decision table when no last-review date
# is on the holding.
REVIEW_CADENCE_DAYS = 30

# Stance → recommended delta direction (used to compute the per-holding $ delta).
_STANCE_TO_DIRECTION = {
    "ADD": +1,
    "RE_ENTER": +1,
    "TRIM": -1,
    "EXIT": -1,
    "HOLD": 0,
    "REVIEW": 0,
}


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _fnum(value: Any, default: float = 0.0) -> float:
    v = _num(value, default)
    return default if v is None else v


# ─────────────────────────────────────────────────────────────────────────────
# Pure policy helpers (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def cash_policy_band(
    portfolio_value: float,
    min_pct: Optional[float] = None,
    max_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Cash policy band in dollars. `min` is the floor; `max` is a soft ceiling."""
    value = max(0.0, _fnum(portfolio_value))
    lo = _fnum(min_pct, CASH_BAND_DEFAULT_MIN_PCT) if min_pct is not None else CASH_BAND_DEFAULT_MIN_PCT
    hi = _fnum(max_pct, CASH_BAND_DEFAULT_MAX_PCT) if max_pct is not None else CASH_BAND_DEFAULT_MAX_PCT
    hi = max(hi, lo)
    return {
        "min_pct": round(lo, 2),
        "max_pct": round(hi, 2),
        "min_usd": round(value * lo / 100.0, 2),
        "max_usd": round(value * hi / 100.0, 2),
    }


def cash_posture(
    cash_total: float,
    portfolio_value: float,
    min_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Classify current cash vs the policy band and split into reserve vs investable.

    ABOVE_BAND  — cash above the floor → the excess is investable dry powder.
    IN_BAND     — cash at/below floor but non-trivial → no force deploy.
    BELOW_BAND  — cash below floor → raise cash, do not deploy.
    """
    cash = max(0.0, _fnum(cash_total))
    value = max(0.0, _fnum(portfolio_value))
    band = cash_policy_band(value, min_pct=min_pct)
    cash_pct = round(cash / value * 100.0, 2) if value > 0 else 0.0
    reserve = band["min_usd"]
    investable = max(0.0, cash - reserve)

    if value <= 0:
        status = "NO_PORTFOLIO"
    elif cash_pct >= band["min_pct"]:
        status = "ABOVE_BAND"
    elif cash >= reserve * 0.5:
        status = "IN_BAND"
    else:
        status = "BELOW_BAND"

    return {
        "cash_usd": round(cash, 2),
        "cash_pct": cash_pct,
        "band_min_pct": band["min_pct"],
        "band_max_pct": band["max_pct"],
        "band_min_usd": band["min_usd"],
        "band_max_usd": band["max_usd"],
        "reserve_usd": round(reserve, 2),
        "investable_usd": round(investable, 2),
        "status": status,
    }


def classify_account_tax(account: str, accounts: Optional[dict[str, Any]] = None) -> str:
    """TAXABLE / TAX_ADVANTAGED / UNKNOWN for one account, from holdings config.

    Unknown accounts are treated as taxable (fail toward applying tax constraints)
    so a tax/lot constraint is never silently waived.
    """
    acct = str(account or "")
    cfg = (accounts or {}).get(acct) or {}
    if isinstance(cfg, dict):
        if cfg.get("taxable") is False:
            return "TAX_ADVANTAGED"
        if cfg.get("taxable") is True:
            return "TAXABLE"
        if str(cfg.get("type") or "").lower() in TAX_ADVANTAGED_TYPES:
            return "TAX_ADVANTAGED"
    # Fallback: infer from the account name itself (ira/roth/401k hints).
    if any(k in acct.lower() for k in ("ira", "roth", "401k", "401(k)")):
        return "TAX_ADVANTAGED"
    return "TAXABLE" if acct else "UNKNOWN"


# ─────────────────────────────────────────────────────────────────────────────
# Pure normalization (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def normalize_position(
    h: dict[str, Any],
    portfolio_value: float,
    accounts: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Normalize one holdings row into a canonical position, or None (cash/empty).

    Idempotent: accepts a raw holdings row (`market_value`) or an already
    normalized position (`market_value_usd`) and returns the canonical shape.
    """
    if not isinstance(h, dict):
        return None
    if h.get("is_cash"):
        return None
    symbol = str(h.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    mv = _fnum(h.get("market_value_usd") if h.get("market_value_usd") is not None
               else h.get("market_value"))
    if mv <= 0:
        return None
    value = max(0.0, _fnum(portfolio_value))
    weight = round(mv / value * 100.0, 2) if value > 0 else 0.0
    account = str(h.get("account") or "")
    return {
        "symbol": symbol,
        "name": h.get("name"),
        "account": account,
        "tax_class": classify_account_tax(account, accounts),
        "market_value_usd": round(mv, 2),
        "weight_pct": weight,
        "quantity": h.get("quantity") or h.get("shares"),
        "asset_type": h.get("asset_type"),
        "last_updated": str(h.get("updated_at") or h.get("as_of") or "") or None,
    }


def _verdict_for(symbol: str, queue: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Best desk verdict/state for one symbol from the opportunity queue (or None)."""
    for it in ((queue or {}).get("items") or (queue or {}).get("top") or []):
        if str(it.get("symbol") or "").upper() == symbol.upper():
            return it
    return None


def stance_for(symbol: str, queue: Optional[dict[str, Any]]) -> str:
    """CIO stance for a symbol across all queue items (Phase 3 semantics).

    Precedence: EXIT > TRIM > RE_ENTER > ADD > reentry state (READY/NEAR) > HOLD.
    Directive labels like "Advisory TRIM — SCHD" count even when verdict is null
    (eliminates HOLD + TRIM contradictions).
    """
    try:
        from scripts.lib.cio_decision_semantics import stance_for_symbol
        return stance_for_symbol(symbol, queue)
    except Exception:
        pass
    # Fail-soft local fallback (single item, verdict/state only).
    # LESS authoritative than the canonical path: free text may NEVER create
    # RE_ENTER here either. Only an explicit governed verdict=RE_ENTER returns
    # RE_ENTER; READY/NEAR/"Re-enter ADBE" text maps to HOLD, never RE_ENTER.
    item = _verdict_for(symbol, queue)
    if not item:
        return "HOLD"
    verdict = str(item.get("verdict") or "").upper().strip() or None
    if verdict in ("EXIT", "TRIM", "RE_ENTER", "ADD"):
        return verdict
    # Desk readiness states are not auto-promoted to RE_ENTER.
    # Label inference fallback without importing — RE_ENTER is deliberately
    # absent so free text can never manufacture a governed re-entry.
    label = str(item.get("directive_label") or item.get("label") or "").upper()
    for needle, stance in (
        ("EXIT", "EXIT"), ("TRIM", "TRIM"), ("ADD", "ADD"),
    ):
        if needle in label:
            return stance
    return "HOLD"

# ─────────────────────────────────────────────────────────────────────────────
# Pure sources & uses (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def build_capital_sources(
    positions: list[dict[str, Any]],
    queue: Optional[dict[str, Any]] = None,
    redeploy_open_events: Optional[list[dict[str, Any]]] = None,
    trim_fraction: float = TRIM_FRACTION,
    *,
    cash_total: Optional[float] = None,
    portfolio_value: Optional[float] = None,
    policy_cap_pct: Optional[float] = None,
    fire_pct: Optional[float] = None,
) -> dict[str, Any]:
    """Sources of funds: trims, exits, and earmarked redeploy proceeds.

    Phase 2 (double-count fix):
      * trims/exits are **prospective** (not yet cash) — they add to total_raise_usd
      * redeploy remaining_usd is **earmarked cash already in cash_total** — tracked
        as maturities_usd / earmarked_redeploy_usd but NOT added to total_raise_usd

    Phase 5: trim dollars use institutional sizing when portfolio_value is known;
    10% remains only a fallback candidate note.

    `cash_total` when provided caps earmarked dollars (cannot earmark more than cash).
    """
    trims: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    port = _fnum(portfolio_value)
    cap = _fnum(policy_cap_pct, MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT)
    fire = _fnum(fire_pct, CONCENTRATION_FIRE_PCT_DEFAULT)

    for p in positions:
        stance = stance_for(p["symbol"], queue)
        if stance == "TRIM":
            # No verified sizing objective (no portfolio context / no fire /
            # no policy breach) means no recommended dollar delta. The tranche
            # size is scenario-only and must not contribute to capital sources.
            note = (
                f"advisory TRIM — no verified sizing objective; "
                f"{trim_fraction:.0%} tranche is scenario-only, recommended delta $0"
            )
            amt = 0.0
            if port > 0:
                try:
                    from scripts.lib.cio_institutional_sizing import (
                        extract_sizing_inputs,
                        size_decision,
                    )
                    sz = size_decision(
                        stance="TRIM",
                        market_value_usd=p["market_value_usd"],
                        weight_pct=p.get("weight_pct") or 0.0,
                        portfolio_value_usd=port,
                        policy_cap_pct=cap,
                        fire_pct=fire,
                        tax_class=str(p.get("tax_class") or "TAXABLE"),
                        **extract_sizing_inputs(p),
                    )
                    amt = abs(_fnum(sz.get("recommended_delta_usd")))
                    note = str(sz.get("objective_summary") or note)
                    if sz.get("fallback_candidate_only"):
                        note = f"{note} [fallback_10pct]"
                except Exception:
                    pass
            if amt > 0:
                trims.append({
                    "symbol": p["symbol"],
                    "account": p.get("account"),
                    "current_value_usd": p["market_value_usd"],
                    "amount_usd": round(amt, 2),
                    "already_in_cash": False,
                    "note": note,
                })
        elif stance == "EXIT":
            exits.append({
                "symbol": p["symbol"],
                "account": p.get("account"),
                "current_value_usd": p["market_value_usd"],
                "amount_usd": p["market_value_usd"],
                "already_in_cash": False,
                "note": "advisory EXIT — full position value released",
            })

    maturities: list[dict[str, Any]] = []
    for ev in redeploy_open_events or []:
        remaining = _fnum((ev or {}).get("remaining_usd"))
        if remaining > 0:
            maturities.append({
                "symbol": str((ev or {}).get("symbol") or "").upper() or None,
                "event_id": (ev or {}).get("event_id") or (ev or {}).get("id"),
                "account": (ev or {}).get("account"),
                "amount_usd": round(remaining, 2),
                "already_in_cash": True,
                "note": "sale proceeds awaiting redeploy — already counted in cash_total",
            })

    trims_usd = round(sum(t["amount_usd"] for t in trims), 2)
    exits_usd = round(sum(e["amount_usd"] for e in exits), 2)
    maturities_raw = round(sum(m["amount_usd"] for m in maturities), 2)
    # Cap earmark at cash on hand (cannot label more redeploy $ than exists as cash)
    cash = _fnum(cash_total) if cash_total is not None else None
    if cash is not None and maturities_raw > cash + 0.01:
        maturities_usd = round(cash, 2)
        capped = True
    else:
        maturities_usd = maturities_raw
        capped = False

    # Prospective only — does NOT include earmarked redeploy
    total_prospective = round(trims_usd + exits_usd, 2)
    total_raise = total_prospective  # alias for deployable arithmetic

    return {
        "trims": trims,
        "exits": exits,
        "maturities_distributions": maturities,
        "trims_usd": trims_usd,
        "exits_usd": exits_usd,
        "maturities_usd": maturities_usd,
        "maturities_raw_usd": maturities_raw,
        "maturities_capped_to_cash": capped,
        "earmarked_redeploy_usd": maturities_usd,
        "total_prospective_raise_usd": total_prospective,
        "total_raise_usd": total_raise,
        "double_count_guard": "earmarked_redeploy_excluded_from_raise",
    }


def _single_name_headroom(
    symbol: str,
    positions: list[dict[str, Any]],
    portfolio_value: float,
    max_single_name_pct: float,
) -> float:
    """Dollar headroom to the single-name cap for a symbol (0 if not applicable)."""
    value = max(0.0, _fnum(portfolio_value))
    cap = max(0.0, _fnum(max_single_name_pct, MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT))
    existing = next((p for p in positions if p["symbol"] == symbol), None)
    current_usd = existing["market_value_usd"] if existing else 0.0
    cap_usd = value * cap / 100.0
    return max(0.0, cap_usd - current_usd)


def build_capital_uses(
    queue: Optional[dict[str, Any]],
    positions: list[dict[str, Any]],
    sector_opportunities: Optional[list[dict[str, Any]]],
    posture: dict[str, Any],
    portfolio_value: float,
    *,
    max_single_name_pct: Optional[float] = None,
    new_position_default_usd: float = NEW_POSITION_DEFAULT_USD,
) -> dict[str, Any]:
    """Uses of funds: adds, new_positions, reentry, sector_rotation, reserve.

    Every deployment use is bounded by single-name headroom (or, for sector
    rotation, by the sector's underweight gap). Reserve is the cash policy floor
    held back — it is a use (cash retained) but never counts as deployment.
    """
    value = max(0.0, _fnum(portfolio_value))
    cap_pct = _fnum(max_single_name_pct, MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT) \
        if max_single_name_pct is not None else MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT

    items = (queue or {}).get("items") or (queue or {}).get("top") or []
    adds: list[dict[str, Any]] = []
    reentry: list[dict[str, Any]] = []
    new_positions: list[dict[str, Any]] = []

    for it in items:
        symbol = str(it.get("symbol") or "").upper()
        verdict = str(it.get("verdict") or "").upper().strip() or None
        state = str(it.get("state") or "").upper().strip() or None
        headroom = _single_name_headroom(symbol, positions, value, cap_pct)

        if verdict == "ADD":
            amt = round(min(new_position_default_usd, headroom) if headroom > 0 else 0.0, 2)
            if amt > 0:
                adds.append({
                    "symbol": symbol,
                    "source": it.get("source"),
                    "amount_usd": amt,
                    "note": it.get("directive_label"),
                })
        elif verdict == "RE_ENTER":
            amt = round(min(new_position_default_usd, headroom) if headroom > 0 else 0.0, 2)
            if amt > 0:
                reentry.append({
                    "symbol": symbol,
                    "source": it.get("source"),
                    "state": state,
                    "amount_usd": amt,
                    "note": it.get("directive_label"),
                })
        elif verdict is None and state is None:
            # desk suggestion without an explicit verdict → candidate for a new
            # position only if it has no existing holding and headroom exists.
            if not any(p["symbol"] == symbol for p in positions) and headroom > 0:
                amt = round(min(new_position_default_usd, headroom), 2)
                new_positions.append({
                    "symbol": symbol,
                    "source": it.get("source"),
                    "amount_usd": amt,
                    "note": it.get("directive_label"),
                })

    rotation: list[dict[str, Any]] = []
    for opp in sector_opportunities or []:
        if not opp.get("opportunity"):
            continue
        current = _num(opp.get("current_exposure_pct"))
        target = _num(opp.get("target_posture_pct"))
        if current is None or target is None or current >= target:
            continue
        gap_pct = target - current
        gap_usd = value * gap_pct / 100.0
        rec = opp.get("recommendation")
        if rec not in ("STAGED_DEPLOYMENT", "RESEARCH_FIRST"):
            continue
        # Sector rotation is a top-up, not a full rebalance; cap the rotate-in at
        # the sector gap (deterministic, advisory).
        if gap_usd > 0:
            rotation.append({
                "sector": opp.get("sector"),
                "etf": opp.get("etf"),
                "state": opp.get("state"),
                "current_pct": round(current, 2),
                "target_pct": round(target, 2),
                "amount_usd": round(gap_usd, 2),
                "recommendation": rec,
                "notional": True,
                "amount_kind": "notional_underweight_gap",
                "note": (
                    "Notional sector underweight gap — not a committed cash ticket; "
                    "included in Total deploy request but labeled separately from "
                    "fundable adds/re-entries."
                ),
            })

    adds_usd = round(sum(a["amount_usd"] for a in adds), 2)
    reentry_usd = round(sum(r["amount_usd"] for r in reentry), 2)
    new_usd = round(sum(n["amount_usd"] for n in new_positions), 2)
    rotation_usd = round(sum(s["amount_usd"] for s in rotation), 2)
    reserve_usd = round(_fnum(posture.get("reserve_usd")), 2)
    fundable_usd = round(adds_usd + reentry_usd + new_usd, 2)
    # Total deploy request = fundable tickets + notional sector-rotation gaps.
    # Reserve is cash retained at the policy floor — never part of this total.
    total_use_usd = round(fundable_usd + rotation_usd, 2)

    return {
        "adds": adds,
        "new_positions": new_positions,
        "reentry": reentry,
        "sector_rotation": rotation,
        "reserve": reserve_usd,
        "adds_usd": adds_usd,
        "reentry_usd": reentry_usd,
        "new_positions_usd": new_usd,
        "sector_rotation_usd": rotation_usd,
        "fundable_deploy_request_usd": fundable_usd,
        "notional_sector_rotation_usd": rotation_usd,
        "total_deploy_request_usd": total_use_usd,
        "reserve_excluded_from_deploy_request": True,
        "deploy_request_reconciled": abs(
            total_use_usd - (fundable_usd + rotation_usd)
        ) < 0.02,
        "component_labels": {
            "adds_usd": "Add to holdings",
            "new_positions_usd": "New positions",
            "reentry_usd": "Re-entry",
            "sector_rotation_usd": "Sector rotation (notional gap)",
            "reserve": "Reserve (held, not deployed)",
            "total_deploy_request_usd": (
                "Total deploy request (fundable + notional sector gaps)"
            ),
            "fundable_deploy_request_usd": "Fundable deploy request",
        },
        "deploy_request_notes": [
            "Total deploy request = adds + new positions + re-entry + sector rotation.",
            "Sector rotation is a notional underweight gap, not a committed cash ticket.",
            "Reserve is the cash-policy floor retained — excluded from Total deploy request.",
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pure plan composition (no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def build_capital_plan(
    *,
    portfolio_value: float,
    cash_total: float,
    positions: list[dict[str, Any]],
    queue: Optional[dict[str, Any]] = None,
    redeploy_open_events: Optional[list[dict[str, Any]]] = None,
    sector_opportunities: Optional[list[dict[str, Any]]] = None,
    accounts: Optional[dict[str, Any]] = None,
    risk_posture: Optional[dict[str, Any]] = None,
    divergence_map: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    cash_band_min_pct: Optional[float] = None,
    max_single_name_pct: Optional[float] = None,
    concentration_fire_pct: Optional[float] = None,
    account_cash: Optional[list[dict[str, Any]]] = None,
    cash_as_of: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build the full Capital Plan projection (advisory only).

    All dollars are deterministic arithmetic over the supplied canonical state.
    Returns the acceptance-shape envelope with a hash-pinned `digest`.
    """
    now = now or datetime.now(timezone.utc)
    rps = risk_posture or {}
    value = max(0.0, _fnum(portfolio_value))
    cash = max(0.0, _fnum(cash_total))

    min_pct = cash_band_min_pct if cash_band_min_pct is not None else _num(
        rps.get("cash_band_min_pct"), CASH_BAND_DEFAULT_MIN_PCT)
    max_name_pct = max_single_name_pct if max_single_name_pct is not None else _num(
        rps.get("max_single_name_weight_pct"), MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT)
    conc_pct = concentration_fire_pct if concentration_fire_pct is not None else _num(
        rps.get("concentration_fire_pct"), CONCENTRATION_FIRE_PCT_DEFAULT)

    # Accept raw or normalized positions; normalize once for all sub-computations.
    norm_positions = [
        p for p in (normalize_position(h, value, accounts) for h in positions)
        if p is not None
    ]

    posture = cash_posture(cash, value, min_pct=min_pct)
    sources = build_capital_sources(
        norm_positions, queue=queue, redeploy_open_events=redeploy_open_events,
        cash_total=cash,
        portfolio_value=value,
        policy_cap_pct=max_name_pct,
        fire_pct=conc_pct,
    )
    uses = build_capital_uses(
        queue, norm_positions, sector_opportunities, posture, value,
        max_single_name_pct=max_name_pct,
    )

    # Phase 2: deployable = investable free cash + prospective trims/exits only.
    # Earmarked redeploy $ is already inside cash_total / investable.
    prospective_raise = sources["total_prospective_raise_usd"]
    earmarked = sources["earmarked_redeploy_usd"]
    deployable = round(posture["investable_usd"] + prospective_raise, 2)
    net_deploy = round(min(uses["total_deploy_request_usd"], deployable), 2)
    net_raise = prospective_raise
    post_cash = round(cash + net_raise - net_deploy, 2)
    post_cash_pct = round(post_cash / value * 100.0, 2) if value > 0 else 0.0

    investable = posture["investable_usd"]
    gap_vs_investable = round(max(0.0, net_deploy - investable), 2)
    deploy_funding = {
        "recommended_deploy_usd": net_deploy,
        "investable_cash_usd": investable,
        "prospective_raise_usd": prospective_raise,
        "deployable_usd": deployable,
        "total_deploy_request_usd": uses["total_deploy_request_usd"],
        "fundable_deploy_request_usd": uses.get("fundable_deploy_request_usd"),
        "notional_sector_rotation_usd": uses.get("notional_sector_rotation_usd"),
        "deploy_exceeds_investable_cash": net_deploy > investable + 0.01,
        "gap_vs_investable_cash_usd": gap_vs_investable,
        "gap_covered_by_prospective_raise": (
            gap_vs_investable > 0 and prospective_raise + 0.01 >= gap_vs_investable
        ),
        "note": (
            f"Recommended deploy ${net_deploy:,.0f} exceeds investable cash "
            f"${investable:,.0f} by ${gap_vs_investable:,.0f}; the gap is funded "
            f"only by prospective raise (trims/exits not yet cash), not by "
            f"reserve or earmarked redeploy."
            if gap_vs_investable > 0.01
            else (
                "Recommended deploy is within investable cash above the policy reserve."
            )
        ),
    }

    # Free cash above earmark (still subject to reserve via investable)
    free_above_earmark = round(max(0.0, cash - earmarked), 2)
    acct_cash = account_cash if account_cash is not None else []
    ledger = build_cash_ledger(
        cash_total=cash,
        portfolio_value=value,
        reserve_usd=posture["reserve_usd"],
        investable_usd=posture["investable_usd"],
        earmarked_redeploy_usd=earmarked,
        prospective_raise_usd=prospective_raise,
        net_deploy_usd=net_deploy,
        post_plan_cash_usd=post_cash,
        account_cash=acct_cash,
    )
    account_ledger = build_account_capital_ledger(
        account_cash=acct_cash,
        positions=norm_positions,
        portfolio_value=value,
        cash_total=cash,
        reserve_usd=posture["reserve_usd"],
        earmarked_redeploy_usd=earmarked,
        prospective_raise_usd=prospective_raise,
        net_deploy_usd=net_deploy,
        post_plan_cash_usd=post_cash,
    )

    position_decisions = build_position_decisions(
        norm_positions, queue=queue, divergence_map=divergence_map,
        portfolio_value=value, max_single_name_pct=max_name_pct,
        concentration_fire_pct=conc_pct,
        accounts=accounts, now=now,
    )

    constraints: list[dict[str, Any]] = [
        {"kind": "cash_band_min_pct", "value": round(_fnum(min_pct), 2),
         "note": "cash held to policy floor before any deployment"},
        {"kind": "max_single_name_weight_pct", "value": round(_fnum(max_name_pct), 2),
         "note": "single-name cap bound for adds/new positions"},
        {"kind": "concentration_fire_pct", "value": round(_fnum(conc_pct), 2),
         "note": "concentration fire threshold"},
        {"kind": "tax_class", "value": "TAXABLE/TAX_ADVANTAGED",
         "note": "taxable accounts carry lot/tax constraints on trims/exits"},
        {"kind": "earmarked_redeploy_not_double_counted", "value": 1,
         "note": "redeploy remaining_usd is labeled earmark inside cash; not added to raise"},
    ]

    plan = {
        "computed_at": now.isoformat(),
        "plan_version": CAPITAL_PLAN_VERSION,
        "authority": "READ_ONLY_ADVISORY",
        # Envelope clock -- when this projection was composed. NOT the age of
        # the cash. `cash_as_of` below carries the cash's own evidence clock.
        "as_of": now.isoformat(),
        "as_of_means": "composition time of this projection, not data age",
        "cash_as_of": cash_as_of if cash_as_of is not None else {
            "as_of": None, "unstamped": True,
            "source": "not supplied by caller",
            "note": "cash age unknown; do not read the envelope clock as its age",
        },
        "portfolio_value_usd": round(value, 2),
        "cash_total_usd": round(cash, 2),
        "cash_reserved_usd": posture["reserve_usd"],
        "cash_investable_usd": posture["investable_usd"],
        "cash_earmarked_redeploy_usd": earmarked,
        "cash_free_unearmarked_usd": free_above_earmark,
        "cash_policy_band": {
            "min_pct": posture["band_min_pct"],
            "max_pct": posture["band_max_pct"],
            "min_usd": posture["band_min_usd"],
            "max_usd": posture["band_max_usd"],
        },
        "cash_posture_status": posture["status"],
        "capital_sources": {
            "trims": sources["trims"],
            "exits": sources["exits"],
            "maturities_distributions": sources["maturities_distributions"],
            "trims_usd": sources["trims_usd"],
            "exits_usd": sources["exits_usd"],
            "maturities_usd": sources["maturities_usd"],
            "earmarked_redeploy_usd": earmarked,
            "total_prospective_raise_usd": prospective_raise,
            "total_raise_usd": sources["total_raise_usd"],
            "double_count_guard": sources.get("double_count_guard"),
            "maturities_capped_to_cash": sources.get("maturities_capped_to_cash"),
        },
        "capital_uses": {
            "adds": uses["adds"],
            "new_positions": uses["new_positions"],
            "reentry": uses["reentry"],
            "sector_rotation": uses["sector_rotation"],
            "reserve": uses["reserve"],
            "adds_usd": uses["adds_usd"],
            "reentry_usd": uses["reentry_usd"],
            "new_positions_usd": uses["new_positions_usd"],
            "sector_rotation_usd": uses["sector_rotation_usd"],
            "fundable_deploy_request_usd": uses.get("fundable_deploy_request_usd"),
            "notional_sector_rotation_usd": uses.get("notional_sector_rotation_usd"),
            "total_deploy_request_usd": uses["total_deploy_request_usd"],
            "reserve_excluded_from_deploy_request": uses.get(
                "reserve_excluded_from_deploy_request", True
            ),
            "deploy_request_reconciled": uses.get("deploy_request_reconciled", True),
            "component_labels": uses.get("component_labels") or {},
            "deploy_request_notes": uses.get("deploy_request_notes") or [],
        },
        "net_recommended_deploy_usd": net_deploy,
        "net_recommended_raise_usd": net_raise,
        "deployable_usd": deployable,
        "deploy_funding": deploy_funding,
        "post_plan_cash_usd": post_cash,
        "post_plan_cash_pct": post_cash_pct,
        "cash_ledger": ledger,
        "account_capital_ledger": account_ledger,
        "earmark_narrative": account_ledger.get("narrative"),
        "ledger_invariants": ledger.get("invariants") or [],
        "portfolio_constraints": constraints,
        "alternatives": _alternatives(plan_deploy=net_deploy, plan_raise=net_raise,
                                      deploy_request=uses["total_deploy_request_usd"],
                                      uncertainty_high=_uncertainty_high(queue, sector_opportunities)),
        "position_decisions": position_decisions,
    }

    key_raw = json.dumps({
        "value": plan["portfolio_value_usd"],
        "cash": plan["cash_total_usd"],
        "reserve": plan["cash_reserved_usd"],
        "earmark": plan["cash_earmarked_redeploy_usd"],
        "raise": plan["net_recommended_raise_usd"],
        "deploy": plan["net_recommended_deploy_usd"],
        "post_cash": plan["post_plan_cash_usd"],
        "positions": [p["symbol"] for p in position_decisions if p.get("recommended_delta_usd")],
        "uses": plan["capital_uses"]["total_deploy_request_usd"],
        "v": CAPITAL_PLAN_VERSION,
    }, sort_keys=True, separators=(",", ":"))
    plan["digest"] = hashlib.sha256(key_raw.encode("utf-8")).hexdigest()
    # G7 ledger identities — attached after digest so they cannot change it.
    try:
        from scripts.lib.cio_capital_invariants import evaluate_capital_invariants
        invs = evaluate_capital_invariants(plan)
        plan["capital_invariants"] = invs
        plan["capital_invariants_ok"] = all(bool(i.get("pass")) for i in invs)
    except Exception:
        pass
    return plan


def capital_invariant_operands(plan: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Expose G7 invariant operands without rewriting sizing."""
    from scripts.lib.cio_capital_invariants import extract_capital_operands
    return extract_capital_operands(plan)


# ─────────────────────────────────────────────────────────────────────────────
# Cash ledger + double-count invariants (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────

# Stamps a cash row may carry, most specific first. `updated_at` is the row's
# write time and is deliberately LAST: it is when the collector touched the row,
# not when the broker last confirmed the balance.
_CASH_STAMP_KEYS = (
    "canonical_mark_as_of", "broker_position_as_of", "as_of", "updated_at",
)


def _cash_row_as_of(h: dict[str, Any]) -> Optional[str]:
    for k in _CASH_STAMP_KEYS:
        v = h.get(k)
        if v:
            return str(v)
    return None


def cash_evidence_as_of(
    holdings_rows: Optional[list[dict[str, Any]]],
    doc: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """The cash block's OWN as-of, derived from the cash rows themselves.

    A capital plan used to stamp its cash with the composition clock -- the
    moment the builder ran. Measured on 2026-08-30 the live book held five cash
    rows spanning 27 days: $500 confirmed 2026-08-03, $5,000 on 2026-08-04, and
    $625,284 of Schwab cash on 2026-08-26. All of it was presented as of today.

    So: report the OLDEST stamp as the block's as-of, because a total is only as
    current as its stalest member; keep the newest and the per-account spread so
    the operator can see which account is dragging; and never fall back to
    ``now``. No stamp anywhere means ``as_of=None`` and ``unstamped=True``,
    which is a visible absence rather than a false freshness.
    """
    rows = [h for h in (holdings_rows or [])
            if isinstance(h, dict) and h.get("is_cash")]
    per: list[dict[str, Any]] = []
    for h in rows:
        per.append({
            "account": str(h.get("account") or h.get("account_id") or "unknown"),
            "settled_cash_usd": round(_fnum(h.get("market_value")), 2),
            "as_of": _cash_row_as_of(h),
        })
    stamps = sorted({p["as_of"] for p in per if p["as_of"]})
    doc_stamp = None
    for k in ("as_of", "generated_at", "updated_at"):
        v = (doc or {}).get(k)
        if v:
            doc_stamp = str(v)
            break
    oldest = stamps[0] if stamps else None
    newest = stamps[-1] if stamps else None
    return {
        "as_of": oldest,
        "oldest_row_as_of": oldest,
        "newest_row_as_of": newest,
        "mixed_ages": bool(len(stamps) > 1),
        "distinct_stamps": len(stamps),
        "unstamped": not stamps,
        "unstamped_accounts": [p["account"] for p in per if not p["as_of"]],
        "by_account": sorted(per, key=lambda p: (p["as_of"] or "", p["account"])),
        "document_as_of": doc_stamp,
        "source": "holdings rows where is_cash, oldest stamp wins",
        "note": (
            "The block is as current as its stalest account, never the moment "
            "the builder ran."
        ),
    }


def account_cash_breakdown(
    holdings_rows: Optional[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Per-account settled cash from holdings rows (is_cash=True), with the
    stamp each account's balance was last confirmed at."""
    by: dict[str, float] = {}
    stamp: dict[str, Optional[str]] = {}
    for h in holdings_rows or []:
        if not isinstance(h, dict) or not h.get("is_cash"):
            continue
        acct = str(h.get("account") or h.get("account_id") or "unknown")
        by[acct] = round(by.get(acct, 0.0) + _fnum(h.get("market_value")), 2)
        s = _cash_row_as_of(h)
        # Oldest contributing row wins, same rule as the block.
        if s and (stamp.get(acct) is None or s < stamp[acct]):
            stamp[acct] = s
    return [{"account": a, "settled_cash_usd": v, "as_of": stamp.get(a)}
            for a, v in sorted(by.items())]


def build_account_capital_ledger(
    *,
    account_cash: Optional[list[dict[str, Any]]],
    positions: list[dict[str, Any]],
    portfolio_value: float,
    cash_total: float,
    reserve_usd: float,
    earmarked_redeploy_usd: float,
    prospective_raise_usd: float,
    net_deploy_usd: float,
    post_plan_cash_usd: float,
) -> dict[str, Any]:
    """Phase 6 — account-level capital ledger for institutional audit.

    Language: earmark is a label on settled cash, never a 'new raise'.
    """
    value = max(0.0, _fnum(portfolio_value))
    cash = max(0.0, _fnum(cash_total))
    reserve = max(0.0, _fnum(reserve_usd))
    earmark = max(0.0, _fnum(earmarked_redeploy_usd))
    prospective = max(0.0, _fnum(prospective_raise_usd))
    deploy = max(0.0, _fnum(net_deploy_usd))
    post = _fnum(post_plan_cash_usd)

    # Index positions by account
    pos_by: dict[str, float] = {}
    for p in positions or []:
        acct = str(p.get("account") or "unknown")
        pos_by[acct] = pos_by.get(acct, 0.0) + _fnum(p.get("market_value_usd") or p.get("market_value"))

    cash_by: dict[str, float] = {}
    for row in account_cash or []:
        if not isinstance(row, dict):
            continue
        acct = str(row.get("account") or "unknown")
        cash_by[acct] = cash_by.get(acct, 0.0) + _fnum(
            row.get("settled_cash_usd") if row.get("settled_cash_usd") is not None else row.get("market_value")
        )

    accounts = sorted(set(list(cash_by.keys()) + list(pos_by.keys())))
    if not accounts:
        accounts = ["portfolio"]
        cash_by["portfolio"] = cash

    # Allocate reserve / earmark / free / prospective / deploy / post by cash share
    rows: list[dict[str, Any]] = []
    for acct in accounts:
        settled = cash_by.get(acct, 0.0)
        share = (settled / cash) if cash > 0 else 0.0
        r_res = round(reserve * share, 2)
        r_ear = round(min(earmark * share, settled), 2)
        r_free = round(max(0.0, settled - r_res), 2)  # investable share proxy
        r_prosp = round(prospective * share, 2)
        r_use = round(deploy * share, 2)
        r_post = round(settled + r_prosp - r_use, 2)
        rows.append({
            "account": acct,
            "settled_cash_usd": round(settled, 2),
            "reserve_allocation_usd": r_res,
            "earmarked_usd": r_ear,
            "free_investable_usd": r_free,
            "prospective_raise_usd": r_prosp,
            "planned_use_usd": r_use,
            "post_plan_cash_usd": r_post,
            "positions_mv_usd": round(pos_by.get(acct, 0.0), 2),
            "negative_cash": r_post < -0.02,
        })

    narrative = (
        f"${earmark:,.0f} of current cash is earmarked from prior exits/redeploy; "
        f"it is not new capital. Prospective raise is ${prospective:,.0f} from "
        f"trims/exits not yet cash. Recommended deploy ${deploy:,.0f} is bounded by "
        f"investable free cash plus prospective raise only."
    )
    return {
        "accounts": rows,
        "portfolio_aggregate": {
            "settled_cash_usd": round(cash, 2),
            "reserve_usd": round(reserve, 2),
            "earmarked_usd": round(earmark, 2),
            "free_unearmarked_usd": round(max(0.0, cash - earmark), 2),
            "prospective_raise_usd": round(prospective, 2),
            "recommended_deploy_usd": round(deploy, 2),
            "post_plan_cash_usd": round(post, 2),
            "portfolio_value_usd": round(value, 2),
        },
        "narrative": narrative,
        "earmark_language": (
            "Do not say 'recommended raise = maturities' when those dollars are already in cash. "
            + narrative
        ),
        "invariants": {
            "earmark_le_settled_cash": earmark <= cash + 0.02,
            "no_negative_account_post_cash": not any(r.get("negative_cash") for r in rows),
            "deploy_le_free_plus_prospective": deploy <= max(0.0, cash - reserve) + prospective + 0.02,
        },
    }


def build_cash_ledger(
    *,
    cash_total: float,
    portfolio_value: float,
    reserve_usd: float,
    investable_usd: float,
    earmarked_redeploy_usd: float,
    prospective_raise_usd: float,
    net_deploy_usd: float,
    post_plan_cash_usd: float,
    account_cash: Optional[list[dict[str, Any]]] = None,
    unsettled_cash_usd: float = 0.0,
) -> dict[str, Any]:
    """First-principles cash layers with double-count invariants.

    Layers (each dollar of cash_total appears once):
      settled_cash_usd     = cash_total (canonical holdings cash)
      unsettled_cash_usd   = optional pending settlement (default 0)
      policy_reserve_usd   = band floor
      earmarked_redeploy   = subset of settled labeled as redeploy proceeds
      free_investable_usd  = investable (settled - reserve), which *includes* earmark
    """
    cash = max(0.0, _fnum(cash_total))
    reserve = max(0.0, _fnum(reserve_usd))
    investable = max(0.0, _fnum(investable_usd))
    earmark = max(0.0, _fnum(earmarked_redeploy_usd))
    prospective = max(0.0, _fnum(prospective_raise_usd))
    deploy = max(0.0, _fnum(net_deploy_usd))
    post = _fnum(post_plan_cash_usd)
    unsettled = max(0.0, _fnum(unsettled_cash_usd))

    invariants: list[dict[str, Any]] = []

    def _inv(name: str, ok: bool, detail: str) -> None:
        invariants.append({"name": name, "ok": ok, "detail": detail})

    _inv(
        "earmark_le_cash",
        earmark <= cash + 0.02,
        f"earmarked_redeploy {earmark:.2f} <= cash {cash:.2f}",
    )
    _inv(
        "investable_eq_cash_minus_reserve",
        abs(investable - max(0.0, cash - reserve)) < 0.02,
        f"investable {investable:.2f} == cash-reserve {max(0.0, cash - reserve):.2f}",
    )
    _inv(
        "post_cash_identity",
        abs(post - (cash + prospective - deploy)) < 0.02,
        f"post {post:.2f} == cash+prospective-deploy "
        f"{cash + prospective - deploy:.2f}",
    )
    _inv(
        "deploy_le_investable_plus_prospective",
        deploy <= investable + prospective + 0.02,
        f"deploy {deploy:.2f} <= investable+prospective {investable + prospective:.2f}",
    )
    # Free unearmarked (informational): cash not labeled redeploy
    free_unearmarked = round(max(0.0, cash - earmark), 2)

    return {
        "settled_cash_usd": round(cash, 2),
        "unsettled_cash_usd": round(unsettled, 2),
        "policy_reserve_usd": round(reserve, 2),
        "earmarked_redeploy_usd": round(earmark, 2),
        "free_unearmarked_usd": free_unearmarked,
        "investable_usd": round(investable, 2),
        "prospective_raise_usd": round(prospective, 2),
        "net_deploy_usd": round(deploy, 2),
        "post_plan_cash_usd": round(post, 2),
        "portfolio_value_usd": round(_fnum(portfolio_value), 2),
        "account_cash": account_cash or [],
        "invariants": invariants,
        "invariants_ok": all(i["ok"] for i in invariants),
        "note": (
            "Earmarked redeploy proceeds are a label on settled cash, not new money. "
            "Prospective trims/exits are the only additive raise."
        ),
    }


def _uncertainty_high(queue: Optional[dict[str, Any]],
                      sector_opportunities: Optional[list[dict[str, Any]]]) -> bool:
    """Uncertainty is 'high' when there is no material multi-desk signal at all."""
    distinct = (queue or {}).get("distinct_sources") or 0
    opp_count = len([o for o in (sector_opportunities or []) if o.get("opportunity")])
    return distinct < 2 and opp_count == 0


def _alternatives(*, plan_deploy: float, plan_raise: float,
                  deploy_request: float, uncertainty_high: bool) -> list[dict[str, Any]]:
    """Provide the 'do nothing' alternative always, plus an implementation variant."""
    alts: list[dict[str, Any]] = [
        {
            "name": "do_nothing",
            "deploy_usd": 0.0,
            "raise_usd": 0.0,
            "post_cash_usd": None,  # filled by caller if needed; kept semantic
            "note": "hold current cash and positions; no new deployment, no trims",
        },
    ]
    if deploy_request > 0 and plan_deploy > 0:
        alts.append({
            "name": "half_sized",
            "deploy_usd": round(plan_deploy * 0.5, 2),
            "raise_usd": round(plan_raise * 0.5, 2),
            "post_cash_usd": None,
            "note": "deploy half the recommended amount to preserve dry powder",
        })
    if uncertainty_high:
        alts.append({
            "name": "await_confluence",
            "deploy_usd": 0.0,
            "raise_usd": 0.0,
            "post_cash_usd": None,
            "note": "wait for multi-desk or sector confluence before sizing any deployment",
        })
    return alts


# ─────────────────────────────────────────────────────────────────────────────
# Position Decision table (pure)
# ─────────────────────────────────────────────────────────────────────────────

def build_position_decisions(
    positions: list[dict[str, Any]],
    *,
    queue: Optional[dict[str, Any]] = None,
    divergence_map: Optional[dict[str, Any]] = None,
    portfolio_value: float = 0.0,
    max_single_name_pct: Optional[float] = None,
    concentration_fire_pct: Optional[float] = None,
    accounts: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Per-holding decision rows for the Position Decision table.

    Every material holding is included. Recommended $ delta uses Phase 5
    institutional sizing (fire/policy objectives; 10% only as fallback).
    """
    now = now or datetime.now(timezone.utc)
    value = max(0.0, _fnum(portfolio_value))
    cap_pct = _fnum(max_single_name_pct, MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT) \
        if max_single_name_pct is not None else MAX_SINGLE_NAME_WEIGHT_PCT_DEFAULT
    fire_pct = _fnum(concentration_fire_pct, CONCENTRATION_FIRE_PCT_DEFAULT) \
        if concentration_fire_pct is not None else CONCENTRATION_FIRE_PCT_DEFAULT

    rows: list[dict[str, Any]] = []
    for p in positions:
        symbol = p["symbol"]
        stance = stance_for(symbol, queue)
        headroom = _single_name_headroom(symbol, positions, value, cap_pct)
        div = (divergence_map or {}).get(symbol) or (divergence_map or {}).get(symbol.lower())

        item = _verdict_for(symbol, queue)
        tax_class = p.get("tax_class") or classify_account_tax(p.get("account"), accounts)
        why = (item or {}).get("directive_label") or "no new desk signal; hold"
        # Prefer a label that matches the resolved stance when multi-desk noise exists.
        try:
            from scripts.lib.cio_decision_semantics import (
                resolve_display_stance, professional_stance, symbol_identity_status,
            )
            stance = resolve_display_stance(stance, why)
            # If primary item is neutral but stance is actionable, find a matching label.
            if stance in ("TRIM", "EXIT", "ADD", "RE_ENTER"):
                for it in ((queue or {}).get("items") or (queue or {}).get("top") or []):
                    if str((it or {}).get("symbol") or "").upper() != symbol:
                        continue
                    lab = (it or {}).get("directive_label") or ""
                    if stance in str(lab).upper() or (
                        stance == "RE_ENTER" and "RE-ENTER" in str(lab).upper()
                    ):
                        why = lab
                        break
            ident = symbol_identity_status(symbol, name=p.get("name"))
            if not ident.get("ok") and not p.get("name"):
                # Unproven identity (CUSIP/ambiguous) without name — skip CIO table
                continue
            stance_display = professional_stance(stance)
        except Exception:
            stance_display = stance
            ident = None

        # Phase 6: candidate-set sizing (10% / $5k are fallback candidates only)
        target_status = None
        try:
            from scripts.lib.cio_institutional_sizing import (
                extract_sizing_inputs,
                size_decision,
            )
            sizing = size_decision(
                stance=stance,
                market_value_usd=p["market_value_usd"],
                weight_pct=p["weight_pct"],
                portfolio_value_usd=value,
                policy_cap_pct=cap_pct,
                fire_pct=fire_pct,
                tax_class=str(tax_class or "TAXABLE"),
                headroom_usd=headroom,
                **extract_sizing_inputs(p),
            )
            delta = float(sizing.get("recommended_delta_usd") or 0.0)
            target_w = sizing.get("target_weight_pct")
            if target_w is None:
                target_w = cap_pct
        except Exception:
            # Sizing failure must make the recommendation LESS actionable, never
            # resurrect the old 10% heuristic. A failed sizing engine cannot
            # authorize a TRIM/EXIT/ADD/RE_ENTER dollar delta, so the row
            # downgrades to REVIEW with $0 (scenario-only note kept for TRIM).
            scenario_trim_usd = (
                round(p["market_value_usd"] * TRIM_FRACTION, 2)
                if stance == "TRIM" else None
            )
            sizing = {
                "method": "SIZING_UNAVAILABLE",
                "fallback_candidate_only": True,
                "sizing_quality": "UNAVAILABLE",
                "candidates": {},
                "scenario_trim_usd": scenario_trim_usd,
                "objective_summary": (
                    "Sizing unavailable — recommendation downgraded to REVIEW "
                    "(no verified dollar delta)."
                ),
            }
            stance = "REVIEW"
            stance_display = "Review"
            delta = 0.0
            target_w = None
            target_status = "UNAVAILABLE"

        risk_txt = (
            "concentration > fire"
            if p["weight_pct"] > fire_pct
            else (
                "concentration > cap"
                if p["weight_pct"] > cap_pct
                else "within single-name cap"
            )
        )
        rows.append({
            "symbol": symbol,
            "name": p.get("name"),
            "account": p.get("account"),
            "current_value_usd": p["market_value_usd"],
            "current_weight_pct": p["weight_pct"],
            "cio_stance": stance,
            "stance": stance_display,
            "stance_code": stance,
            "target_range_pct": {"min": 0.0, "max": round(cap_pct, 2)},
            "target_weight_pct": (
                None
                if target_status == "UNAVAILABLE"
                else (round(float(target_w), 2) if target_w is not None else round(cap_pct, 2))
            ),
            "target_status": target_status,
            "recommended_delta_usd": round(delta, 2),
            "funding": _funding_for(stance, delta),
            "why_now": why,
            "risk": risk_txt,
            "tax_account_constraint": _tax_constraint(tax_class, stance),
            "counter_thesis": str(div) if div else "no Street/desk disagreement on record",
            "next_review": _next_review(p.get("last_updated"), now),
            "identity": ident,
            "sizing": sizing,
            "sizing_method": sizing.get("method"),
            "sizing_objective": sizing.get("objective_summary"),
            "sizing_why_not_min": sizing.get("why_not_min"),
            "sizing_why_not_max": sizing.get("why_not_max"),
            "trim_to_clear_fire_usd": sizing.get("trim_to_clear_fire_usd"),
            "trim_to_policy_usd": sizing.get("trim_to_policy_usd"),
            "scenario_trim_usd": sizing.get("scenario_trim_usd"),
            "fallback_candidate_only": bool(sizing.get("fallback_candidate_only")),
            "candidates": sizing.get("candidates"),
            "sizing_quality": sizing.get("sizing_quality"),
            "selected_candidate": sizing.get("selected_candidate"),
            "selection_rationale": sizing.get("selection_rationale"),
            "tranches": sizing.get("tranches"),
            "tax_class": tax_class,
            "decision_generated_at": _decision_source_clock(p, now),
            "decision_revalidated_at": None,
            "decision_input_digest": _decision_digest(symbol, stance, delta, p),
            "decision_evidence_digest": _decision_digest(symbol, stance, delta, p, extra="evidence"),
            "decision_policy_version": "capital_plan_1.3.0",
            "decision_revalidation_reason": "builder_ran_not_evidence_revalidation",
            # Keep generated_at as the evidence clock, never "now".
            "generated_at": _decision_source_clock(p, now),
            "revalidated_at": None,
        })

    rows.sort(key=lambda r: (-abs(r["recommended_delta_usd"]), -r["current_value_usd"]))
    # Phase 3: also attach aggregated-by-symbol view for operator surfaces
    try:
        from scripts.lib.cio_decision_semantics import aggregate_position_decisions
        aggregated = aggregate_position_decisions(rows, portfolio_value=value)
        # Prefer aggregated list as the primary decision table (one row per symbol)
        if aggregated:
            for a in aggregated:
                a.setdefault("generated_at", a.get("decision_generated_at") or _decision_source_clock(a, now))
                a.setdefault("revalidated_at", a.get("decision_revalidated_at"))
                a.setdefault("decision_input_digest", a.get("decision_input_digest"))
            return aggregated
    except Exception:
        pass
    return rows

def _decision_source_clock(pos: dict[str, Any], now: datetime) -> str:
    """Evidence clock — never 'builder ran now'."""
    for key in (
        "canonical_mark_as_of", "source_as_of", "price_as_of", "quote_time",
        "broker_position_as_of", "last_updated",
    ):
        v = pos.get(key)
        if v:
            return str(v)
    # Last resort: date-only as-of, still not wall-clock now.
    return now.date().isoformat()


def _decision_digest(symbol: str, stance: str, delta: float, pos: dict[str, Any], extra: str = "") -> str:
    # Single recipe lives in cio_decision_semantics (no cycle: semantics never
    # imports this module).
    from scripts.lib.cio_decision_semantics import decision_content_digest
    return decision_content_digest(symbol, stance, delta, pos, extra=extra)


def _funding_for(stance: str, delta: float) -> str:
    if stance == "EXIT":
        return "release to cash (source of funds)"
    if stance == "TRIM":
        return "trim to cash (source of funds)"
    if stance in ("ADD", "RE_ENTER"):
        return "investable cash / raised cash (use of funds)"
    return "none"


def _tax_constraint(tax_class: str, stance: str) -> str:
    if tax_class == "TAX_ADVANTAGED":
        return "tax-advantaged: no lot/tax drag on rebalance"
    if stance in ("TRIM", "EXIT"):
        return "taxable: lot/tax-basis review before realizing"
    return "taxable: buy side only, no gain realization"


def _next_review(last_updated: Optional[str], now: datetime) -> Optional[str]:
    if not last_updated:
        return None
    try:
        ts = datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        from datetime import timedelta
        return (ts + timedelta(days=REVIEW_CADENCE_DAYS)).date().isoformat()
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Live reader (injectable sources; separated from pure logic)
# ─────────────────────────────────────────────────────────────────────────────

def load_holdings_snapshot(holdings_doc: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Read holdings.json into the normalized portfolio dict (fail-soft)."""
    doc = holdings_doc or {}
    holdings = doc.get("holdings") or []
    totals = doc.get("portfolio_totals") or {}
    config = doc.get("config") or {}
    accounts_raw = config.get("accounts") or {}

    accounts: dict[str, Any] = {}
    for name, cfg in accounts_raw.items():
        if isinstance(cfg, dict):
            accounts[str(name)] = cfg

    total_value = _fnum(totals.get("total_value"))
    cash = sum(_fnum(h.get("market_value")) for h in holdings if h.get("is_cash"))
    # Portfolio value may exclude some MV; use holdings-derived total as fallback.
    derived_total = sum(_fnum(h.get("market_value")) for h in holdings)
    if total_value <= 0 and derived_total > 0:
        total_value = derived_total
    if total_value <= 0:
        total_value = cash  # all-cash edge

    positions = [normalize_position(h, total_value, accounts) for h in holdings]
    positions = [p for p in positions if p is not None]
    acct_cash = account_cash_breakdown(holdings)

    return {
        "portfolio_value": total_value,
        "cash_total": cash,
        "positions": positions,
        "accounts": accounts,
        "account_cash": acct_cash,
        "cash_as_of": cash_evidence_as_of(holdings, doc),
    }


def build_capital_plan_from_sources(
    *,
    holdings_doc: Optional[dict[str, Any]] = None,
    queue: Optional[dict[str, Any]] = None,
    redeploy_open_events: Optional[list[dict[str, Any]]] = None,
    sector_opportunities: Optional[list[dict[str, Any]]] = None,
    risk_posture: Optional[dict[str, Any]] = None,
    divergence_map: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
    attach_financial_truth_gate: bool = True,
) -> dict[str, Any]:
    """Compose the full plan from already-fetched canonical state (convenience).

    Phase 2 (acceptance): optionally attaches FinancialTruthGate so ACT NOW
    consumers can suppress conflicted symbols without formatting around errors.
    """
    snap = load_holdings_snapshot(holdings_doc)
    plan = build_capital_plan(
        portfolio_value=snap["portfolio_value"],
        cash_total=snap["cash_total"],
        positions=snap["positions"],
        accounts=snap["accounts"],
        queue=queue,
        redeploy_open_events=redeploy_open_events,
        sector_opportunities=sector_opportunities,
        risk_posture=risk_posture,
        divergence_map=divergence_map,
        now=now,
        account_cash=snap.get("account_cash"),
        cash_as_of=snap.get("cash_as_of"),
    )
    if attach_financial_truth_gate and holdings_doc is not None:
        try:
            from scripts.lib.cio_financial_truth_gate import (
                evaluate_holdings_document,
                attach_gate_to_capital_plan,
            )
            gate = evaluate_holdings_document(
                holdings_doc,
                now=now,
                portfolio_value_override=snap.get("portfolio_value"),
            )
            plan = attach_gate_to_capital_plan(plan, gate)
        except Exception as exc:  # fail-soft — plan still returns
            plan = dict(plan)
            plan["financial_truth_gate"] = {
                "ok": False,
                "overall_quality": "ERROR",
                "error": str(exc)[:200],
                "authority": "READ_ONLY_ADVISORY",
            }
        # Phase 3: freshness + materiality — ACT NOW never from delta alone
        try:
            from scripts.lib.cio_freshness_materiality_gate import attach_to_capital_plan as _attach_fm
            plan = _attach_fm(plan, holdings_doc=holdings_doc, now=now)
        except Exception as exc:
            plan = dict(plan)
            plan["freshness_materiality_gate"] = {
                "version": "freshness_materiality_1.0.0",
                "error": str(exc)[:200],
                "authority": "READ_ONLY_ADVISORY",
            }
    # Phases 11–16: retrieve research/seasonality BEFORE strategy_context.
    # research_context is a modifier note only — never creates TRIM from August.
    try:
        from scripts.lib.cio_seasonality_engine import build_seasonality_context
        from scripts.lib.cio_strategy_knowledge import (
            load_strategy_store,
            compose_strategy_context,
        )
        from scripts.lib.cio_research_retriever import retrieve_research_context
        season = build_seasonality_context(now)
        symbols = [
            str(p.get("symbol"))
            for p in (snap.get("positions") or [])
            if p.get("symbol")
        ]
        research = retrieve_research_context(
            now,
            symbols=symbols,
            decision_id=str(plan.get("decision_id") or plan.get("digest") or "") or None,
        )
        store = load_strategy_store()
        plan = dict(plan)
        plan["seasonality"] = season
        plan["research_context"] = research
        plan["strategy_context"] = compose_strategy_context(
            now=now,
            store=store,
            seasonality=season,
            research_context=research,
            symbols=symbols,
        )
    except Exception as exc:
        plan = dict(plan)
        plan["strategy_context"] = {
            "error": str(exc)[:200],
            "role": "risk_modifier_or_context",
            "authority": "READ_ONLY_ADVISORY",
        }
    # Phase 7: decision field parity self-check on plan surface
    try:
        from scripts.lib.cio_decision_semantics import decision_field_parity
        plan = dict(plan)
        plan["decision_field_parity"] = decision_field_parity(
            plan.get("position_decisions") or [],
        )
    except Exception as exc:
        plan = dict(plan)
        plan["decision_field_parity"] = {
            "ok": False, "error": str(exc)[:200], "authority": "READ_ONLY_ADVISORY",
        }
    # Phase 8: attach compact provenance on top material decisions
    try:
        from scripts.lib.cio_advisory_provenance import build_expanded_row_provenance
        plan = dict(plan)
        rows = list(plan.get("position_decisions") or [])
        # Build a holdings lookup by symbol for price/MV facts
        hmap: dict[str, dict] = {}
        if holdings_doc and isinstance(holdings_doc, dict):
            for h in holdings_doc.get("holdings") or holdings_doc.get("positions") or []:
                if isinstance(h, dict) and h.get("symbol"):
                    sym = str(h["symbol"]).upper()
                    # Prefer highest MV row if multi-account
                    prev = hmap.get(sym)
                    if prev is None or float(h.get("market_value") or 0) > float(prev.get("market_value") or 0):
                        hmap[sym] = h
        enriched = []
        for d in rows:
            dd = dict(d)
            base = hmap.get(str(d.get("symbol") or "").upper()) or {}
            merged = {**base, **{k: v for k, v in d.items() if v is not None}}
            try:
                dd["advisory_provenance"] = build_expanded_row_provenance(merged)
            except Exception:
                pass
            enriched.append(dd)
        plan["position_decisions"] = enriched
    except Exception as exc:
        plan = dict(plan)
        plan["advisory_provenance_error"] = str(exc)[:200]
    return plan
