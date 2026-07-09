"""csp_generator.py — cash-secured put (entry / income) paper proposal generator.

Models CSP at the watchlist entry-plan limit (or zone low) when the operator
has expressed willingness to own at that strike. Thesis gating lives in
strategy_matcher; this module handles contract selection and gates only.

SAFETY: same paper-model flags as atm_long_premium_generator (educational only).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .deep_itm_generator import PAPER_MODEL_BLOCK, IV_RICH_FLAG, _f, _proposal_id, apply_iv_edge_modifier

FAMILY = "income_entry"
STRATEGY = "cash_secured_put"

DEFAULT_SELECTION_POLICY: Dict[str, Any] = {
    "dte_buckets": [30, 45],
    "max_spread_pct": 10.0,
    "min_open_interest": 100,
    "min_volume": 1,
    "max_premium_pct_of_underlying": 12.0,
    "max_contracts_paper": 1,
    "strike_tolerance_pct": 0.08,
    "allow_strike_above_plan": False,
}

EXECUTION_NOTE = (
    "PAPER MODEL — cash-secured put at entry-plan strike (willingness-to-own). "
    "Manual review only; verify buying power and assignment risk before entry."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bucket_expiration(snapshot: dict, target_dte: int) -> Optional[dict]:
    best, best_gap = None, None
    for exp in snapshot.get("expirations") or []:
        gap = abs(int(_f(exp.get("dte"))) - int(target_dte))
        if best_gap is None or gap < best_gap:
            best, best_gap = exp, gap
    if best is None:
        return None
    tolerance = max(12, round(int(target_dte) * 0.45))
    return best if best_gap is not None and best_gap <= tolerance else None


def _select_put_at_strike(exp: dict, spot: float, target_strike: float, policy: dict) -> Optional[dict]:
    puts = [c for c in (exp.get("contracts") or []) if c.get("side") == "put"]
    if not puts:
        return None
    tol = _f(policy.get("strike_tolerance_pct"), 0.08)
    allow_above = bool(policy.get("allow_strike_above_plan"))
    candidates = []
    for c in puts:
        strike = _f(c.get("strike"))
        if strike <= 0:
            continue
        if not allow_above and strike > target_strike * (1 + tol):
            continue
        if strike < target_strike * (1 - tol):
            continue
        dist = abs(strike - target_strike)
        candidates.append((dist, c))
    if not candidates:
        # nearest OTM put at or below target
        below = [c for c in puts if _f(c.get("strike")) <= target_strike]
        pool = below or puts
        candidates = [(abs(_f(c.get("strike")) - target_strike), c) for c in pool]
    candidates.sort(key=lambda x: (x[0], -int(_f(x[1].get("liquidity_score")))))
    return candidates[0][1] if candidates else None


def _csp_metrics(c: dict, spot: float) -> dict:
    mid = c.get("mid")
    strike = _f(c.get("strike"))
    intrinsic = round(max(strike - spot, 0.0), 4)
    breakeven = round(strike - mid, 4) if mid is not None else None
    row = {
        "strike": strike,
        "exp": c.get("exp"),
        "dte": c.get("dte"),
        "bid": c.get("bid"),
        "ask": c.get("ask"),
        "mid": mid,
        "delta": c.get("delta"),
        "iv": c.get("iv"),
        "volume": c.get("volume"),
        "oi": c.get("oi"),
        "spread_pct": c.get("spread_pct"),
        "liquidity_score": c.get("liquidity_score"),
        "intrinsic_value": intrinsic,
        "extrinsic_value": round(mid - intrinsic, 4) if mid is not None else None,
        "breakeven": breakeven,
        "flags": {"no_quote": mid is None},
    }
    if mid is not None:
        credit = round(mid * 100.0, 2)
        row["premium"] = round(mid, 4)
        row["premium_total"] = credit
        row["max_profit"] = credit
        row["max_loss"] = round(max((strike - mid) * 100.0, 0.0), 2)
        row["capital_required"] = round(strike * 100.0, 2)
        row["premium_pct_of_underlying"] = round(mid / spot * 100.0, 2) if spot else None
    return row


def evaluate_csp_gates(candidate: dict, policy: dict) -> Dict[str, Any]:
    rejects: List[str] = []
    flags: List[str] = []
    mid = candidate.get("mid")
    if mid is None or mid <= 0:
        rejects.append("no quote")
    spread = candidate.get("spread_pct")
    if spread is not None and _f(spread) > _f(policy.get("max_spread_pct"), 10.0):
        rejects.append(f"spread {_f(spread):.1f}% > max")
    oi = int(_f(candidate.get("oi")))
    if oi < int(policy.get("min_open_interest") or 100):
        rejects.append(f"OI {oi} < min")
    vol = int(_f(candidate.get("volume")))
    if vol < int(policy.get("min_volume") or 1):
        rejects.append(f"volume {vol} < min")
    pct = candidate.get("premium_pct_of_underlying")
    if pct is not None and _f(pct) > _f(policy.get("max_premium_pct_of_underlying"), 12.0):
        rejects.append(f"premium {_f(pct):.1f}% of spot > max")
    return {"pass": not rejects, "rejects": rejects, "flags": flags}


def generate_csp_proposals(
    symbol: str,
    thesis_ctx: dict,
    *,
    target_strike: Optional[float] = None,
    snapshot: Optional[dict] = None,
    chain_fn: Optional[Callable[..., dict]] = None,
    iv_context: Optional[dict] = None,
    config: Optional[dict] = None,
) -> dict:
    """Model CSP at ``target_strike`` (entry-plan limit / zone low)."""
    sym = (symbol or "").strip().upper()
    policy = dict(DEFAULT_SELECTION_POLICY)
    if config and config.get("selection_policy"):
        policy.update(config["selection_policy"])

    strike_target = _f(target_strike)
    if strike_target <= 0:
        return {"available": False, "reason": "no entry-plan strike (willingness-to-own undefined)",
                "proposals": [], "symbol": sym}

    snap = snapshot
    if snap is None:
        if chain_fn is None:
            try:
                from lib.strategy_research.options_chain import fetch_chain_snapshot as chain_fn  # noqa: F811
            except Exception as e:
                return {"available": False, "reason": f"chain import failed: {e}",
                        "proposals": [], "symbol": sym}
        try:
            snap = chain_fn(sym)
        except Exception as e:
            return {"available": False, "reason": str(e)[:120], "proposals": [], "symbol": sym}

    if not snap or not snap.get("available"):
        return {"available": False, "reason": (snap or {}).get("reason") or "chain unavailable",
                "proposals": [], "symbol": sym, "degraded": True}

    spot = _f(snap.get("underlying_price"))
    if spot <= 0:
        return {"available": False, "reason": "underlying price missing", "proposals": [], "symbol": sym}

    iv_ctx = iv_context or {"available": False}
    proposals: List[dict] = []
    buckets_out: List[dict] = []

    for target_dte in policy.get("dte_buckets") or [30, 45]:
        exp = _bucket_expiration(snap, int(target_dte))
        if not exp:
            buckets_out.append({"target_dte": target_dte, "available": False,
                                "reason": "no expiration in DTE window"})
            continue
        raw = _select_put_at_strike(exp, spot, strike_target, policy)
        if not raw:
            buckets_out.append({"target_dte": target_dte, "available": False,
                                "reason": f"no put near plan strike ${strike_target:.2f}"})
            continue
        cand = _csp_metrics(raw, spot)
        gate = evaluate_csp_gates(cand, policy)
        bucket = {"target_dte": target_dte, "exp": exp.get("exp"), "dte": exp.get("dte"),
                  "available": gate["pass"], "selected": cand if gate["pass"] else None,
                  "gate": gate}
        buckets_out.append(bucket)
        if not gate["pass"]:
            continue

        mid = cand.get("mid")
        strike = cand.get("strike")
        exp_s = cand.get("exp")
        edge_base = _f(cand.get("liquidity_score")) * 0.55 + _f(thesis_ctx.get("conviction")) * 40
        edge, _ = apply_iv_edge_modifier(edge_base, iv_ctx)
        disclosed = list(gate.get("flags") or [])
        if thesis_ctx.get("cio_avoid_with_plan"):
            disclosed.append("cio_avoid_conflicts_with_entry_plan")
        if iv_ctx.get("available") and iv_ctx.get("verdict") == "extrinsic_rich":
            disclosed.append(IV_RICH_FLAG)

        reasoning = [
            f"CSP at plan strike ${strike:.2f} (target ${strike_target:.2f})",
            f"credit ${(mid or 0) * 100:,.0f} · max loss ${cand.get('max_loss'):,.0f}",
            f"breakeven ${cand.get('breakeven'):.2f} — willing-to-own entry overlay",
            f"thesis: {thesis_ctx.get('conviction_source') or 'entry_plan'}",
        ]
        if disclosed:
            reasoning.append("flags: " + ", ".join(disclosed))

        proposals.append({
            "id": _proposal_id(STRATEGY, sym, "paper_model", strike, exp_s),
            "strategy": STRATEGY,
            "strategy_family": FAMILY,
            "symbol": sym,
            "underlying": sym,
            "account": "",
            "side": "SELL",
            "option_type": "put",
            "strike": strike,
            "expiration": exp_s,
            "dte": cand.get("dte"),
            "contracts": 1,
            "premium": round(mid, 2) if mid else None,
            "premium_total": cand.get("premium_total"),
            "underlying_price": round(spot, 2),
            "max_profit": cand.get("max_profit"),
            "max_loss": cand.get("max_loss"),
            "breakeven": cand.get("breakeven"),
            "edge_score": round(edge, 1),
            "iv_rank": iv_ctx.get("iv_rank") if iv_ctx.get("available") else None,
            "delta": cand.get("delta"),
            "oi": cand.get("oi"),
            "volume": cand.get("volume"),
            "spread_pct": cand.get("spread_pct"),
            "liquidity_score": cand.get("liquidity_score"),
            "recommended_action": "Review Cash-Secured Put (paper model)",
            "reasoning": " · ".join(reasoning),
            "educational_paper_model": True,
            "requires_manual_review": True,
            "paper_only": True,
            "execution_mode": "manual_review_only",
            "auto_eligible": False,
            "execution_note": EXECUTION_NOTE,
            "enterprise": {"live_eligible": False, "blocks": [PAPER_MODEL_BLOCK], "paper_model": True},
            "meta": {"gate_flags": disclosed, "plan_strike": strike_target,
                     "selection_policy": policy},
        })

    if not proposals:
        notes = "; ".join(
            f"{b.get('target_dte')}d: {b.get('reason') or ', '.join((b.get('gate') or {}).get('rejects') or [])}"
            for b in buckets_out if not b.get("available"))
        return {"available": True, "symbol": sym, "proposals": [], "buckets": buckets_out,
                "reason": "no candidates passed gates" + (f" ({notes})" if notes else "")}

    return {"available": True, "symbol": sym, "proposals": proposals, "buckets": buckets_out,
            "generated_at": _now_iso()}