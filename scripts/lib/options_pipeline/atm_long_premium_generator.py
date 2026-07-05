"""atm_long_premium_generator.py — ATM call/put (directional long premium) paper
proposal generator (MULTI-STRATEGY OPTIONS Stage 1, operator spec Part B).

Pipeline: one underlying + side → read-only chain snapshot
(lib.strategy_research.options_chain.fetch_chain_snapshot — the SAME AST-proven
read path the deep-ITM lane uses) → per-DTE-bucket contract selection in the
ATM delta window (|delta| 0.45-0.60; nearest-the-money proxy when the chain
carries no usable greeks, disclosed) → registry/config gates (spread / OI /
volume / premium-pct-of-underlying / paper premium cap / earnings policy) →
edge score (fit × liquidity × conviction, IV-rank modifier reused from the
deep-ITM lane) → proposal rows in the EXACT desk-queue shape the deep-ITM
generator emits (options_approval_queue, manual-review lane).

Thesis gating (bullish for atm_call, bearish for atm_put) is OWNED by
lib.options_pipeline.strategy_matcher — this module models contracts, the
matcher decides whether the strategy applies at all.

SAFETY INVARIANTS (test-enforced by tests/test_options_pipeline_atm.py):
  • Every proposal carries educational_paper_model=True, requires_manual_review=True,
    paper_only=True, execution_mode='manual_review_only', auto_eligible=False.
  • enterprise.live_eligible is ALWAYS False with an explicit paper-model block, so
    options_desk_enterprise.resolve_approval refuses live approval and
    check_preflight_approval refuses live submit (desk fail-closed gates).
  • Registry caps are enforced: 1 contract, debit <= max_premium_paper ($5000).
  • No broker submit / order / 2FA module is imported here — chain reads happen
    inside the AST-proven read-only options_chain research adapter.
  • Chains degrade honestly (weekends/holidays/no link) — a degraded underlying
    yields an explicit reason, never fabricated numbers.
  • This module writes NOTHING — queue writes belong to Stage 2's scanner (which
    reuses deep_itm_generator.submit_to_desk_queue, itself fail-closed).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# Shared conventions — REUSED, never re-implemented (same package, no broker surface).
from .deep_itm_generator import (
    PAPER_MODEL_BLOCK,
    IV_RICH_FLAG,
    _f,
    _proposal_id,
    apply_iv_edge_modifier,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

FAMILY = "directional_long_premium"
STRATEGY_BY_SIDE: Dict[str, str] = {"call": "atm_call", "put": "atm_put"}
SIDE_BY_STRATEGY: Dict[str, str] = {v: k for k, v in STRATEGY_BY_SIDE.items()}

RECOMMENDED_ACTION = {
    "call": "Review ATM Call (paper model)",
    "put": "Review ATM Put (paper model)",
}
EXECUTION_NOTE_TEMPLATE = (
    "PAPER MODEL — educational directional-long-premium analysis (ATM {side}). "
    "Manual review only; no auto-execution, no live order path. Outcomes feed the "
    "{strategy} validation gate (30 paper outcomes, PF>1.3, WR>55%) before any "
    "live consideration."
)

# Earnings policy values (operator spec Part A): flag = disclosed card flag
# (default), block = hard reject.
EARNINGS_POLICY_FLAG = "flag"
EARNINGS_POLICY_BLOCK = "block"
EARNINGS_FLAG = "earnings_before_expiry_flagged"

DELTA_PROXY_FLAG = "delta_proxy_nearest_the_money"

DEFAULT_SELECTION_POLICY: Dict[str, Dict[str, Any]] = {
    "atm_call": {
        "delta_range": [0.45, 0.60],
        "dte_buckets": [30, 45, 60],
        "max_spread_pct": 8.0,
        "min_open_interest": 300,
        "min_volume": 10,
        "max_premium_pct_of_underlying": 8.0,
        "earnings_policy": EARNINGS_POLICY_FLAG,
        "allow_delta_proxy": True,
        "atm_proxy_band_pct": 0.05,
        "max_underlyings_per_run": 15,
        "max_proposals_per_run": 5,
        "max_candidates_per_bucket": 3,
        "max_premium_paper": 5000.0,
        "max_contracts_paper": 1,
    },
    "atm_put": {
        "delta_range": [-0.60, -0.45],
        "dte_buckets": [30, 45, 60],
        "max_spread_pct": 8.0,
        "min_open_interest": 300,
        "min_volume": 10,
        "max_premium_pct_of_underlying": 8.0,
        "earnings_policy": EARNINGS_POLICY_FLAG,
        "allow_delta_proxy": True,
        "atm_proxy_band_pct": 0.05,
        "max_underlyings_per_run": 15,
        "max_proposals_per_run": 5,
        "max_candidates_per_bucket": 3,
        "max_premium_paper": 5000.0,
        "max_contracts_paper": 1,
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strategy_for(side_or_strategy: str) -> str:
    s = (side_or_strategy or "").strip().lower()
    if s in STRATEGY_BY_SIDE:
        return STRATEGY_BY_SIDE[s]
    if s in SIDE_BY_STRATEGY:
        return s
    raise ValueError(f"unknown ATM side/strategy {side_or_strategy!r} "
                     f"(known: {sorted(STRATEGY_BY_SIDE)} / {sorted(SIDE_BY_STRATEGY)})")


def load_pipeline_config(side_or_strategy: str) -> dict:
    """Strategy YAML (config/strategies/atm_call.yaml | atm_put.yaml) with policy
    defaults filled and the strategy-registry gates overlaid (registry is the
    gate source of record; the YAML mirrors it).

    A LivePolicyViolation from the registry loader is NEVER swallowed — a
    registry claiming live permission poisons the whole options stack
    (fail-closed). Other registry outages degrade to the YAML/default gates.
    """
    strategy = _strategy_for(side_or_strategy)
    try:
        from strategy_config_loader import load_strategy_config
        cfg = load_strategy_config(strategy) or {}
    except Exception:
        cfg = {}
    policy = dict(DEFAULT_SELECTION_POLICY[strategy])
    policy.update(cfg.get("selection_policy") or {})

    # Registry overlay — liquidity_gates + selection + paper caps win over YAML.
    from .universe import LivePolicyViolation, load_strategy_registry
    try:
        row = (load_strategy_registry().get("strategies") or {}).get(strategy) or {}
        gates = row.get("liquidity_gates") or {}
        if gates.get("max_spread_pct") is not None:
            policy["max_spread_pct"] = float(gates["max_spread_pct"])
        if gates.get("min_oi") is not None:
            policy["min_open_interest"] = int(gates["min_oi"])
        if gates.get("min_volume") is not None:
            policy["min_volume"] = int(gates["min_volume"])
        sel = row.get("selection") or {}
        for k in ("delta_range", "dte_buckets", "max_premium_pct_of_underlying",
                  "earnings_policy"):
            if sel.get(k) is not None:
                policy[k] = sel[k]
        if row.get("max_premium_paper") is not None:
            policy["max_premium_paper"] = float(row["max_premium_paper"])
        if row.get("max_contracts_paper") is not None:
            policy["max_contracts_paper"] = int(row["max_contracts_paper"])
    except LivePolicyViolation:
        raise  # the live-policy wall is NEVER swallowed (fail-closed)
    except Exception:
        pass   # other registry outages keep the YAML/default gates
    cfg["selection_policy"] = policy
    cfg.setdefault("strategy_id", strategy)
    cfg.setdefault("family", FAMILY)
    cfg.setdefault("paper_only", True)
    cfg.setdefault("execution_mode", "manual_review_only")
    cfg.setdefault(
        "underlying_quality_gate",
        {"conviction_floor": 0.55, "include_current_holdings": True},
    )
    return cfg


# ── per-bucket contract selection over a parsed chain snapshot ───────────────

def _bucket_expiration(snapshot: dict, target_dte: int) -> Optional[dict]:
    """Closest expiration to the bucket target, within a sane tolerance
    (same rule as options_chain._bucket_expiration — a 90-DTE expiry must not
    masquerade as the 30-day bucket)."""
    best, best_gap = None, None
    for exp in snapshot.get("expirations") or []:
        gap = abs(int(_f(exp.get("dte"))) - int(target_dte))
        if best_gap is None or gap < best_gap:
            best, best_gap = exp, gap
    if best is None:
        return None
    tolerance = max(15, round(int(target_dte) * 0.4))
    return best if best_gap is not None and best_gap <= tolerance else None


def _select_bucket_candidates(exp: dict, side: str, spot: float,
                              policy: dict) -> dict:
    """Contracts of ``side`` in the ATM delta window for one expiration.

    Greeks path: |delta| inside the configured window. Proxy path (no usable
    greeks anywhere on the side, and allow_delta_proxy): strikes within
    ±atm_proxy_band_pct of spot — nearest-the-money, disclosed via
    selection_mode. Returns {"mode", "candidates", "reason"?}.
    """
    lo, hi = sorted(abs(float(x)) for x in (policy.get("delta_range")
                                            or DEFAULT_SELECTION_POLICY["atm_call"]["delta_range"]))
    contracts = [c for c in (exp.get("contracts") or []) if c.get("side") == side]
    if not contracts:
        return {"mode": None, "candidates": [],
                "reason": f"no {side} contracts at this expiration"}
    with_delta = [c for c in contracts if c.get("delta") is not None]
    if with_delta:
        # parse_chain normalizes deltas via abs() — compare on |delta| for both sides
        in_band = [c for c in with_delta if lo <= abs(float(c["delta"])) <= hi]
        if not in_band:
            return {"mode": "delta", "candidates": [],
                    "reason": f"no {side}s with |delta| in [{lo}, {hi}]"}
        mode = "delta"
    else:
        if not policy.get("allow_delta_proxy", True):
            return {"mode": "no_greeks", "candidates": [],
                    "reason": "chain carries no usable greeks and delta proxy is disallowed"}
        band_pct = _f(policy.get("atm_proxy_band_pct"), 0.05)
        in_band = [c for c in contracts
                   if abs(_f(c.get("strike")) - spot) / spot <= band_pct]
        if not in_band:
            return {"mode": "atm_proxy", "candidates": [],
                    "reason": f"no {side}s within ±{band_pct:.0%} of spot (proxy band)"}
        mode = "atm_proxy"
    ranked = sorted(in_band, key=lambda c: (-int(_f(c.get("liquidity_score"))),
                                            abs(_f(c.get("strike")) - spot)))
    cap = max(1, int(policy.get("max_candidates_per_bucket") or 3))
    return {"mode": mode, "candidates": ranked[:cap]}


# ── candidate math (long premium, per side) ──────────────────────────────────

def _candidate_metrics(c: dict, side: str, spot: float,
                       earnings: Optional[str]) -> dict:
    """Premium / breakeven / max-loss math for one ATM contract. Every figure
    comes from actual chain rows; a missing mid yields honest Nones."""
    mid = c.get("mid")
    strike = _f(c.get("strike"))
    if side == "call":
        intrinsic = round(max(spot - strike, 0.0), 4)
        breakeven = round(strike + mid, 4) if mid is not None else None
    else:
        intrinsic = round(max(strike - spot, 0.0), 4)
        breakeven = round(strike - mid, 4) if mid is not None else None
    extrinsic = round(mid - intrinsic, 4) if mid is not None else None
    ebe = _earnings_before(c.get("exp") or "", earnings)
    row = {
        "strike": strike, "exp": c.get("exp"), "dte": c.get("dte"),
        "bid": c.get("bid"), "ask": c.get("ask"), "mid": mid,
        "delta": c.get("delta"), "iv": c.get("iv"),
        "volume": c.get("volume"), "oi": c.get("oi"),
        "spread_pct": c.get("spread_pct"),
        "liquidity_score": c.get("liquidity_score"),
        "intrinsic_value": intrinsic,
        "extrinsic_value": extrinsic,
        "breakeven": breakeven,
        "breakeven_move_pct": (round((breakeven / spot - 1.0) * 100.0, 2)
                               if breakeven is not None and spot else None),
        "flags": {"no_quote": mid is None, "earnings_before_expiry": ebe},
    }
    if mid is not None:
        debit = round(mid * 100.0, 2)
        row["premium"] = round(mid, 4)
        row["max_loss"] = debit                       # long premium: max loss = debit
        row["capital_required"] = debit
        row["premium_pct_of_underlying"] = (round(mid / spot * 100.0, 2)
                                            if spot else None)
        row["max_profit"] = ("unlimited" if side == "call"
                             else round(max(strike - mid, 0.0) * 100.0, 2))
    else:
        row["premium"] = None
        row["max_loss"] = None
        row["capital_required"] = None
        row["premium_pct_of_underlying"] = None
        row["max_profit"] = None
    return row


def _earnings_before(exp: str, earnings: Optional[str]) -> Optional[bool]:
    if not earnings or not exp:
        return None
    try:
        return str(earnings)[:10] <= str(exp)[:10]
    except Exception:
        return None


# ── gates (registry-sourced) over one candidate ──────────────────────────────

def evaluate_atm_gates(candidate: dict, bucket: dict, policy: dict) -> Dict[str, Any]:
    """Apply the registry/config gates to one candidate-metrics row.

    Returns {"pass": bool, "rejects": [...], "flags": [...], "selection_mode"}.
    Rejections are honest machine-readable reasons; flags are non-fatal
    disclosures (delta proxy, earnings flagged under the 'flag' policy).
    """
    rejects: List[str] = []
    flags: List[str] = []
    mode = bucket.get("selection_mode") or "delta"

    if candidate.get("mid") is None:
        rejects.append("no_quotable_mid")
    if mode == "atm_proxy":
        flags.append(DELTA_PROXY_FLAG)

    # DTE bucket membership
    buckets = [int(b) for b in (policy.get("dte_buckets") or [])]
    if int(bucket.get("target_dte") or 0) not in buckets:
        rejects.append(f"dte_bucket_{bucket.get('target_dte')}_not_configured")

    # Spread
    spread = candidate.get("spread_pct")
    max_spread = _f(policy.get("max_spread_pct"), 8.0)
    if spread is None:
        if candidate.get("mid") is not None:
            rejects.append("spread_unquotable")
    elif float(spread) > max_spread:
        rejects.append(f"spread_{float(spread):.1f}pct_gt_{max_spread}")

    # Open interest / volume
    oi = int(_f(candidate.get("oi")))
    if oi < int(policy.get("min_open_interest") or 0):
        rejects.append(f"oi_{oi}_lt_{policy.get('min_open_interest')}")
    vol = int(_f(candidate.get("volume")))
    if vol < int(policy.get("min_volume") or 0):
        rejects.append(f"volume_{vol}_lt_{policy.get('min_volume')}")

    # Premium efficiency vs underlying
    ppct = candidate.get("premium_pct_of_underlying")
    cap = _f(policy.get("max_premium_pct_of_underlying"), 8.0)
    if ppct is None:
        if candidate.get("mid") is not None:
            rejects.append("premium_pct_unknown")
    elif float(ppct) > cap:
        rejects.append(f"premium_{float(ppct):.1f}pct_of_underlying_gt_{cap:g}")

    # Paper premium cap (registry: 1 contract, max_premium_paper)
    debit = candidate.get("max_loss")
    prem_cap = _f(policy.get("max_premium_paper"), 5000.0)
    if debit is not None and float(debit) > prem_cap:
        rejects.append(f"debit_{float(debit):.0f}_gt_max_premium_paper_{prem_cap:.0f}")

    # Earnings before expiry — per operator earnings_policy
    ebe = (candidate.get("flags") or {}).get("earnings_before_expiry")
    epolicy = str(policy.get("earnings_policy") or EARNINGS_POLICY_FLAG).lower()
    if ebe is True:
        if epolicy == EARNINGS_POLICY_BLOCK:
            rejects.append("earnings_before_expiry")
        else:
            flags.append(EARNINGS_FLAG)
    elif ebe is None:
        flags.append("earnings_unknown")

    return {"pass": not rejects, "rejects": rejects, "flags": flags,
            "selection_mode": mode}


# ── scoring ──────────────────────────────────────────────────────────────────

def score_candidate(candidate: dict, spot: float, conviction: float) -> float:
    """Edge base = mean(ATM-fit, liquidity) × conviction (0-100 scale).

    ATM fit: 100 at the money, decaying 12.5 points per 1% of moneyness
    distance (0 at ±8% — the premium-efficiency horizon). No fabricated
    inputs — missing pieces lower the score, they are never invented.
    """
    liq = _f(candidate.get("liquidity_score"))
    strike = _f(candidate.get("strike"))
    fit = 0.0
    if spot and strike:
        moneyness_pct = abs(strike - spot) / spot * 100.0
        fit = max(0.0, 100.0 - moneyness_pct * 12.5)
    base = (fit + liq) / 2.0
    conv = max(0.0, min(1.0, _f(conviction, 0.0)))
    return round(base * conv, 1)


# ── proposal row (EXACT desk-queue shape — mirrors deep_itm_generator) ────────

def _build_proposal_row(
    strategy: str,
    side: str,
    sym: str,
    spot: float,
    bucket: dict,
    candidate: dict,
    gate_result: dict,
    iv_ctx: dict,
    thesis_ctx: dict,
    config: dict,
) -> dict:
    exp = str(bucket.get("exp") or "")
    strike = candidate.get("strike")
    mid = _f(candidate.get("mid"))
    conviction = _f(thesis_ctx.get("conviction"), 0.0)
    edge_base = score_candidate(candidate, spot, conviction)
    edge, iv_mod = apply_iv_edge_modifier(edge_base, iv_ctx)
    delta = candidate.get("delta")

    disclosed_flags = list(gate_result.get("flags") or [])
    if iv_ctx.get("available") and iv_ctx.get("verdict") == "extrinsic_rich":
        disclosed_flags.append(IV_RICH_FLAG)

    try:
        import options_desk_enterprise as ent
        tier = ent.desk_tier(edge)
    except Exception:
        tier = "A" if edge >= 72 else ("B" if edge >= 62 else "C")

    direction = "bullish" if side == "call" else "bearish"
    reasoning_bits = [
        (f"ATM {side} directional long premium: Δ{abs(float(delta)):.2f}"
         if delta is not None
         else f"ATM {side} directional long premium (nearest-the-money proxy — "
              "chain carried no greeks)"),
        f"debit ${(mid or 0) * 100:,.0f} "
        f"({_f(candidate.get('premium_pct_of_underlying')):.1f}% of underlying), "
        f"max loss = debit",
        f"breakeven ${_f(candidate.get('breakeven')):.2f} "
        f"({_f(candidate.get('breakeven_move_pct')):+.1f}%)",
        f"{direction} thesis: {thesis_ctx.get('conviction_source') or 'unknown'} "
        f"(conviction {conviction:.0%})",
    ]
    if iv_ctx.get("available"):
        reasoning_bits.append(
            f"IV rank {_f(iv_ctx.get('iv_rank')):.0f}% — "
            f"{iv_ctx.get('verdict_label') or iv_ctx.get('verdict')}")
    if disclosed_flags:
        reasoning_bits.append("flags: " + ", ".join(disclosed_flags))
    reasoning_bits.append("PAPER MODEL — manual review only, never auto-executed")

    execution_note = EXECUTION_NOTE_TEMPLATE.format(side=side, strategy=strategy)
    row = {
        "id": _proposal_id(strategy, sym, "paper_model", strike, exp),
        "strategy": strategy,
        "strategy_family": FAMILY,
        "symbol": sym,
        "underlying": sym,
        "account": "",
        "account_display": "Paper Model (educational)",
        "broker": "paper_model",
        "side": "BUY",
        "option_type": side,
        "strike": strike,
        "expiration": exp,
        "dte": bucket.get("dte"),
        "contracts": int(_f((config.get("selection_policy") or {})
                            .get("max_contracts_paper"), 1.0)) or 1,
        "premium": round(mid, 2) if mid is not None else None,
        "premium_total": round(mid * 100.0, 2) if mid is not None else None,
        "underlying_price": round(spot, 2),
        "pop_pct": round(abs(float(delta)) * 100.0, 1) if delta is not None else None,
        "max_profit": candidate.get("max_profit"),
        "max_loss": candidate.get("max_loss"),
        "breakeven": candidate.get("breakeven"),
        "breakeven_move_pct": candidate.get("breakeven_move_pct"),
        "intrinsic_value": candidate.get("intrinsic_value"),
        "extrinsic_value": candidate.get("extrinsic_value"),
        "premium_pct_of_underlying": candidate.get("premium_pct_of_underlying"),
        "risk_reward": None,
        "expected_value": None,
        "edge_score": edge,
        "iv_rank": (round(_f(iv_ctx.get("iv_rank")), 1)
                    if iv_ctx.get("available") and iv_ctx.get("iv_rank") is not None
                    else None),
        "iv_context": iv_ctx,
        "delta": delta,
        "oi": candidate.get("oi"),
        "volume": candidate.get("volume"),
        "spread_pct": candidate.get("spread_pct"),
        "liquidity_score": candidate.get("liquidity_score"),
        "severity": "info",
        "recommended_action": RECOMMENDED_ACTION[side],
        "action_buttons": [
            {"action": "review_chain", "label": "View Chain"},
            {"action": "hold", "label": "Pass"},
        ],
        "reasoning": " · ".join(reasoning_bits),
        "quality_pass": True,
        "data_source": "schwab_chain",
        # ── paper/educational lane flags (HARD SAFETY — test-enforced) ──
        "educational_paper_model": True,
        "requires_manual_review": True,
        "paper_only": True,
        "execution_mode": "manual_review_only",
        "execution_label": "Paper model · manual review only",
        "auto_eligible": False,
        "execution_note": execution_note,
        "desk_tier": tier,
        "enterprise": {
            "tier": tier,
            "live_eligible": False,          # desk fail-closed: approve + submit both refuse
            "blocks": [PAPER_MODEL_BLOCK],
            "earnings": {
                "in_blackout": bool((candidate.get("flags") or {})
                                    .get("earnings_before_expiry")),
                "next_earnings": thesis_ctx.get("next_earnings_date"),
            },
            "liquidity": {
                "pass": True,
                "oi": candidate.get("oi"),
                "volume": candidate.get("volume"),
                "bid_ask_spread_pct": candidate.get("spread_pct"),
                "mid": candidate.get("mid"),
                "issues": [],
            },
            "vol_analytics": None,
            "approval_required": True,
            "paper_model": True,
        },
        "meta": {
            "strategy_json": {
                "strategy_id": strategy,
                "family": FAMILY,
                "side": side,
                "direction": direction,
                "display_name": config.get("display_name") or strategy,
                "selection_policy": dict(config.get("selection_policy") or {}),
            },
            "selection_mode": gate_result.get("selection_mode"),
            "gate_flags": disclosed_flags,
            "iv_edge": {"base_edge": edge_base, "modifier": iv_mod,
                        "adjusted_edge": edge,
                        "verdict": iv_ctx.get("verdict") if iv_ctx.get("available") else None},
            "underlying_intel": {
                "conviction": conviction,
                "conviction_source": thesis_ctx.get("conviction_source"),
                "watchlist_verdict": thesis_ctx.get("verdict"),
                "held_shares": thesis_ctx.get("held_shares"),
                "hedge_of_held": bool(thesis_ctx.get("hedge_of_held")),
                "thesis_direction": direction,
            },
            "dte_bucket": {
                "target_dte": bucket.get("target_dte"),
                "exp": bucket.get("exp"),
                "dte": bucket.get("dte"),
            },
            "analysis": {
                "strategy": strategy,
                "underlying_price": spot,
                "delta_range": list((config.get("selection_policy") or {})
                                    .get("delta_range") or []),
                "next_earnings_date": thesis_ctx.get("next_earnings_date"),
                "iv_context": iv_ctx,
                "candidate": candidate,
                "generated_at": _now_iso(),
            },
        },
        "generated_at": _now_iso(),
    }
    return row


# ── main generator (operator spec Part B API) ────────────────────────────────

def generate_atm_proposals(
    underlying: Any,
    side: str,
    config: Optional[dict] = None,
    thesis_ctx: Optional[dict] = None,
    *,
    snapshot: Optional[dict] = None,
    chain_fn: Optional[Callable[..., dict]] = None,
    earnings_date: Optional[str] = None,
    iv_context: Optional[dict] = None,
) -> dict:
    """ATM long-premium paper proposals for ONE underlying + side.

    underlying: symbol string or a dict carrying at least {"symbol"}; extra keys
    (conviction, verdict, held_shares, ...) merge into thesis_ctx.
    side: "call" (atm_call) or "put" (atm_put).
    thesis_ctx: {conviction, conviction_source, verdict, held_shares,
    hedge_of_held, ...} — informs scoring + disclosure. Thesis PASS/FAIL is the
    strategy_matcher's job, not this generator's.
    snapshot / chain_fn / earnings_date / iv_context are injectable for tests;
    defaults use the read-only research adapters.

    Returns {"strategy", "symbol", "side", "available", "proposals", "buckets",
    "count", ...}. Chain-unavailable underlyings degrade honestly with a reason.
    """
    strategy = _strategy_for(side)
    side = SIDE_BY_STRATEGY[strategy]
    if isinstance(underlying, dict):
        sym = (underlying.get("symbol") or "").strip().upper()
        merged_ctx = dict(underlying)
    else:
        sym = str(underlying or "").strip().upper()
        merged_ctx = {}
    merged_ctx.update(thesis_ctx or {})
    merged_ctx.setdefault("conviction", 0.60)

    cfg = config or load_pipeline_config(strategy)
    policy = dict(DEFAULT_SELECTION_POLICY[strategy])
    policy.update(cfg.get("selection_policy") or {})
    cfg = dict(cfg, selection_policy=policy)

    base = {"strategy": strategy, "symbol": sym, "side": side,
            "family": FAMILY, "generated_at": _now_iso()}
    if not sym:
        return {**base, "available": False, "reason": "no symbol given",
                "count": 0, "proposals": [], "buckets": []}

    snap = snapshot
    if snap is None:
        if chain_fn is None:
            from lib.strategy_research.options_chain import fetch_chain_snapshot as chain_fn  # noqa: F811
        snap = chain_fn(sym)
    if not (snap or {}).get("available"):
        return {**base, "available": False,
                "reason": (snap or {}).get("reason") or "chain unavailable",
                "count": 0, "proposals": [], "buckets": []}
    spot = _f(snap.get("underlying_price"))
    if not spot or spot <= 0:
        return {**base, "available": False,
                "reason": "chain carried no underlying price — refusing to "
                          "compute moneyness from fabricated data",
                "count": 0, "proposals": [], "buckets": []}

    # Earnings + IV context (read-only, honest degrades)
    earnings = earnings_date
    if earnings is None:
        try:
            from lib.strategy_research.options_chain import next_earnings_date
            earnings = next_earnings_date(sym)
        except Exception:
            earnings = None
    merged_ctx["next_earnings_date"] = earnings
    iv_ctx = iv_context
    if iv_ctx is None:
        try:
            from lib.strategy_research import iv_history
            atm = iv_history.extract_atm_iv(snap)
            iv_ctx = iv_history.iv_rank(sym, current_iv=(atm or {}).get("atm_iv"))
        except Exception as e:
            iv_ctx = {"available": False, "reason": f"iv context error: {str(e)[:120]}"}

    proposals: List[dict] = []
    buckets_out: List[dict] = []
    seen: set = set()   # (strike, exp) — adjacent buckets may share an expiration
    for target in (policy.get("dte_buckets") or []):
        exp = _bucket_expiration(snap, int(target))
        if exp is None:
            buckets_out.append({"target_dte": int(target), "available": False,
                                "reason": "no expiration near this DTE bucket"})
            continue
        sel = _select_bucket_candidates(exp, side, spot, policy)
        bucket = {"target_dte": int(target), "exp": exp.get("exp"),
                  "dte": exp.get("dte"), "selection_mode": sel.get("mode")}
        if not sel["candidates"]:
            buckets_out.append({**bucket, "available": False,
                                "reason": sel.get("reason") or "no candidates"})
            continue
        reject_notes: List[str] = []
        kept = None
        for raw in sel["candidates"]:
            c = dict(raw, exp=exp.get("exp"),
                     dte=int(_f(raw.get("dte")) or _f(exp.get("dte"))))
            candidate = _candidate_metrics(c, side, spot, earnings)
            key = (candidate.get("strike"), candidate.get("exp"))
            if key in seen:
                reject_notes.append(f"${candidate.get('strike')}: already selected "
                                    "by an adjacent bucket")
                continue
            gate = evaluate_atm_gates(candidate, bucket, policy)
            if gate["pass"]:
                kept = _build_proposal_row(strategy, side, sym, spot, bucket,
                                           candidate, gate, iv_ctx, merged_ctx, cfg)
                seen.add(key)
                break
            reject_notes.append(f"${candidate.get('strike')}: "
                                + ",".join(gate["rejects"]))
        if kept:
            proposals.append(kept)
            buckets_out.append({**bucket, "available": True,
                                "proposal_id": kept["id"],
                                "reject_notes": reject_notes[:4]})
        else:
            buckets_out.append({**bucket, "available": False,
                                "reason": "no candidate passed gates",
                                "reject_notes": reject_notes[:4]})

    proposals.sort(key=lambda p: -_f(p.get("edge_score")))
    proposals = proposals[:max(1, int(policy.get("max_proposals_per_run") or 5))]
    return {
        **base,
        "available": True,
        "underlying_price": spot,
        "next_earnings_date": earnings,
        "iv_context": iv_ctx,
        "count": len(proposals),
        "proposals": proposals,
        "buckets": buckets_out,
    }


if __name__ == "__main__":
    # Smoke: config load only (generation is driven by the Stage 2 scanner / matcher)
    print(json.dumps({
        "atm_call_config_loaded": bool(load_pipeline_config("atm_call")),
        "atm_put_config_loaded": bool(load_pipeline_config("atm_put")),
        "family": FAMILY,
    }, indent=2))
